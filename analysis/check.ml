(* Copyright (c) 2016-present, Facebook, Inc.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree. *)

open Core
open Ast
module Error = AnalysisError
open Pyre

module type Signature = sig
  val name : string

  val run
    :  configuration:Configuration.Analysis.t ->
    environment:TypeEnvironment.t ->
    source:Source.t ->
    unit
end

let checks : (module Signature) String.Map.t =
  let checks : (string * (module Signature)) list =
    [
      "awaitable", (module AwaitableCheck);
      "deobfuscation", (module DeobfuscationCheck);
      "immutable_collection", (module ImmutableCollectionCheck);
      "inference", (module Inference);
      "liveness", (module LivenessCheck);
      "typeCheck", (module TypeCheck);
    ]
  in
  String.Map.of_alist_exn checks


let get_check_to_run ~check_name = Map.find checks check_name

let create_check ~configuration:{ Configuration.Analysis.infer; additional_checks; _ }
    : (module Signature)
  =
  let checks_to_run = if infer then ["inference"] else "typeCheck" :: additional_checks in
  let find name =
    match Map.find checks name with
    | Some check -> Some check
    | None ->
        Log.warning "Could not find check `%s`." name;
        None
  in
  let filtered_checks = List.filter_map checks_to_run ~f:find in
  let module AggregatedCheck : Signature = struct
    let name = String.concat checks_to_run ~sep:", "

    let run ~configuration ~environment ~source =
      let run_one_check (module Check : Signature) =
        Check.run ~configuration ~environment ~source
      in
      List.iter filtered_checks ~f:run_one_check
  end
  in
  (module AggregatedCheck)


let run_check
    ?open_documents
    ~scheduler
    ~configuration
    ~environment
    checked_sources
    (module Check : Signature)
  =
  let number_of_sources = List.length checked_sources in
  Log.info "Running check `%s`..." Check.name;
  let timer = Timer.start () in
  let map _ qualifiers =
    Annotated.Class.AttributeCache.clear ();
    AstEnvironment.FromEmptyStubCache.clear ();
    let analyze_source
        number_files
        ({ Source.source_path = { SourcePath.qualifier; _ }; _ } as source)
      =
      let configuration =
        match open_documents with
        | Some predicate when predicate qualifier ->
            { configuration with Configuration.Analysis.store_type_check_resolution = true }
        | _ -> configuration
      in
      Check.run ~configuration ~environment ~source;
      number_files + 1
    in
    let ast_environment = TypeEnvironment.ast_environment environment in
    List.filter_map qualifiers ~f:(AstEnvironment.ReadOnly.get_source ast_environment)
    |> List.fold ~init:0 ~f:analyze_source
  in
  let reduce left right =
    let number_files = left + right in
    Log.log ~section:`Progress "Processed %d of %d sources" number_files number_of_sources;
    number_files
  in
  let _ =
    Scheduler.map_reduce
      scheduler
      ~configuration
      ~bucket_size:75
      ~initial:0
      ~map
      ~reduce
      ~inputs:checked_sources
      ()
  in
  Statistics.performance ~name:(Format.asprintf "check_%s" Check.name) ~timer ();
  Statistics.event
    ~section:`Memory
    ~name:"shared memory size post-typecheck"
    ~integers:["size", Memory.heap_size ()]
    ();
  ()


let analyze_sources
    ?open_documents
    ?(filter_external_sources = true)
    ~scheduler
    ~configuration
    ~environment
    sources
  =
  let ast_environment = TypeEnvironment.ast_environment environment in
  Annotated.Class.AttributeCache.clear ();
  let checked_sources =
    if filter_external_sources then
      let is_not_external qualifier =
        AstEnvironment.ReadOnly.get_source_path ast_environment qualifier
        >>| (fun { SourcePath.is_external; _ } -> not is_external)
        |> Option.value ~default:false
      in
      List.filter sources ~f:is_not_external
    else
      sources
  in
  let number_of_sources = List.length checked_sources in
  Log.info "Checking %d sources..." number_of_sources;
  Profiling.track_shared_memory_usage ~name:"Before analyze_sources" ();
  let timer = Timer.start () in
  run_check
    ?open_documents
    ~scheduler
    ~configuration
    ~environment
    checked_sources
    (create_check ~configuration);
  Statistics.performance ~name:"analyzed sources" ~phase_name:"Type check" ~timer ();
  Profiling.track_shared_memory_usage ~name:"After analyze_sources" ()


let postprocess_sources ~scheduler ~configuration ~environment sources =
  Log.log ~section:`Progress "Postprocessing...";
  let map _ modules = Postprocessing.run ~modules environment in
  let reduce = List.append in
  Scheduler.map_reduce
    scheduler
    ~configuration
    ~bucket_size:200
    ~initial:[]
    ~map
    ~reduce
    ~inputs:sources
    ()


let analyze_and_postprocess
    ?open_documents
    ?filter_external_sources
    ~scheduler
    ~configuration
    ~environment
    sources
  =
  analyze_sources
    ?open_documents
    ?filter_external_sources
    ~scheduler
    ~configuration
    ~environment
    sources;
  postprocess_sources
    ~scheduler
    ~configuration
    ~environment:(TypeEnvironment.read_only environment)
    sources
