(** Copyright (c) 2016-present, Facebook, Inc.

    This source code is licensed under the MIT license found in the
    LICENSE file in the root directory of this source tree. *)

open Core

open Ast
open Expression
open Pyre
open Statement


module Error = AnalysisError


let name =
  "ConstantPropagation"


module type Context = sig
  val configuration: Configuration.Analysis.t
  val environment: (module Environment.Handler)
  val transformations: Statement.t Location.Reference.Table.t
end


module State (Context: Context) = struct
  type constant =
    | Constant of Expression.t
    | Top


  and nested_define = {
    nested_define: Define.t;
    state: t;
  }


  and t = {
    constants: constant Access.Map.t;
    define: Define.t;
    nested_defines: nested_define Location.Reference.Map.t;
  }


  let show { constants; _ } =
    let print_entry (access, constant) =
      let pp_constant format = function
        | Constant expression -> Format.fprintf format "Constant %a" Expression.pp expression
        | Top -> Format.fprintf format "Top"
      in
      Format.asprintf
        "%a -> %a"
        Access.pp access
        pp_constant constant
    in
    Map.to_alist constants
    |> List.map ~f:print_entry
    |> String.concat ~sep:", "


  let pp format state =
    Format.fprintf format "%s" (show state)


  let initial ~state ~define =
    let constants =
      match state with
      | Some { constants; _ } -> constants
      | _ -> Access.Map.empty
    in
    { constants; define; nested_defines = Location.Reference.Map.empty }


  let nested_defines { nested_defines; _ } =
    Map.data nested_defines


  let less_or_equal ~left:{ constants = left; _ } ~right:{ constants = right; _ } =
    let less_or_equal (access, constant) =
      match constant, Map.find right access with
      | _, Some Top -> true
      | Constant left, Some (Constant right) when Expression.equal left right -> true
      | _ -> false
    in
    Map.to_alist left
    |> List.for_all ~f:less_or_equal


  let join left right =
    let merge ~key:_ = function
      | `Both (Constant left, Constant right) when Expression.equal left right ->
          Some (Constant left)
      | _ ->
          Some Top
    in
    { left with constants = Map.merge left.constants right.constants ~f:merge }


  let widen ~previous ~next ~iteration:_ =
    join previous next


  let forward
      ?key
      ({ constants; define = { Define.name; parent; _ }; nested_defines } as state)
      ~statement =
    let resolution =
      TypeCheck.resolution_with_key
        ~environment:Context.environment
        ~parent
        ~access:name
        ~key
    in

    (* Update transformations. *)
    let transformed =
      let transform statement =
        let module Transform =
          Transform.Make(struct
            type t = unit
            let expression _ expression =
              match Node.value expression with
              | Access access ->
                  begin
                    let rec transform ~lead ~tail =
                      match tail with
                      | head :: tail ->
                          begin
                            let lead = lead @ [head] in
                            match Map.find constants lead with
                            | Some (Constant { Node.value = Access access; _ }) ->
                                access @ tail
                            | Some (Constant expression) ->
                                Access.Expression expression :: tail
                            | _ ->
                                transform ~lead ~tail
                          end
                      | _ ->
                          lead
                    in
                    match transform ~lead:[] ~tail:access with
                    | [Access.Expression expression] -> expression
                    | access -> Access.expression access ~location:(Node.location expression)
                  end
              | _ ->
                  expression
            let transform_children _ _ =
              true
            let statement _ statement =
              (), [statement]
          end)
        in
        Source.create [statement]
        |> Transform.transform ()
        |> Transform.source
        |> Source.statements
        |> function
        | [statement] -> statement
        | _ -> failwith "Could not transform statement"
      in
      match Node.value statement with
      | Assign ({ value; _ } as assign) ->
          (* Do not update left hand side of assignment. *)
          let value =
            Statement.Expression value
            |> Node.create_with_default_location
            |> transform
            |> function
            | { Node.value = Statement.Expression value; _ } -> value
            | _ -> failwith "Could not extract expression"
          in
          { statement with Node.value = Assign { assign with value }}
      | _ ->
          transform statement
    in
    if not (Statement.equal statement transformed) then
      Hashtbl.set Context.transformations ~key:(Node.location transformed) ~data:transformed;

    (* Find new constants. *)
    let constants =
      match Node.value transformed with
      | Assign { target = { Node.value = Access access; _ }; value = expression; _ }  ->
          let propagate =
            let is_literal =
              match Node.value expression with
              | Integer _ | String _ | True | False -> true
              | _ -> false
            in
            let is_callable =
              Resolution.resolve resolution expression
              |> (fun annotation -> Type.is_callable annotation || Type.is_meta annotation)
            in
            let is_global_constant =
              match Node.value expression with
              | Access access ->
                  Str.string_match (Str.regexp ".*\\.[A-Z_0-9]+$") (Access.show access) 0
              | _ ->
                  false
            in
            is_literal || is_callable || is_global_constant
          in
          if propagate then
            Map.set constants ~key:access ~data:(Constant expression)
          else
            Map.remove constants access
      | _ ->
          constants
    in

    let state = { state with constants } in

    let nested_defines =
      match statement with
      | { Node.location; value = Define nested_define } ->
          Map.set nested_defines ~key:location ~data:{ nested_define; state }
      | _ ->
          nested_defines
    in

    { state with nested_defines }


  let backward ?key:_ _ ~statement:_ =
    failwith "Not implemented"
end


let run
    ~configuration
    ~environment
    ~source:({ Source.qualifier; statements; handle; _ } as source) =
  let module Context =
  struct
    let configuration = configuration
    let environment = environment
    let transformations = Location.Reference.Table.create ()
  end
  in
  let module State = State(Context) in
  let module Fixpoint = Fixpoint.Make(State) in

  (* Collect transformations. *)
  let rec run ~state ~define =
    Fixpoint.forward ~cfg:(Cfg.create define) ~initial:(State.initial ~state ~define)
    |> Fixpoint.exit
    >>| (fun state ->
        State.nested_defines state
        |> List.iter
          ~f:(fun { State.nested_define; state } -> run ~state:(Some state) ~define:nested_define))
    |> ignore
  in
  let define = Define.create_toplevel ~qualifier ~statements in
  run ~state:None ~define;

  (* Apply transformations. *)
  let source =
    let module Transform =
      Transform.MakeStatementTransformer(struct
        type t = unit
        let statement _ statement =
          let transformed =
            Hashtbl.find Context.transformations (Node.location statement)
            |> Option.value ~default:statement
          in
          (), [transformed]
      end)
    in
    Transform.transform () source
    |> Transform.source
  in

  let location = Location.Reference.create_with_handle ~handle in
  [
    Error.create
      ~location
      ~kind:(Error.ConstantPropagation source)
      ~define:(Node.create define ~location);
  ]
