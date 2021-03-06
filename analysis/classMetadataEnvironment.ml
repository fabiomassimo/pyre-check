(* Copyright (c) 2016-present, Facebook, Inc.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree. *)

open Core
open Ast
open Pyre
module PreviousEnvironment = ClassHierarchyEnvironment

type t = { class_hierarchy_environment: ClassHierarchyEnvironment.ReadOnly.t }

let create class_hierarchy_environment = { class_hierarchy_environment }

type class_metadata = {
  successors: Type.Primitive.t list;
  is_test: bool;
  is_final: bool;
  extends_placeholder_stub_class: bool;
}
[@@deriving eq, compare, show]

module ClassMetadataValue = struct
  type t = class_metadata

  let prefix = Prefix.make ()

  let description = "Class metadata"

  let unmarshall value = Marshal.from_string value 0

  let compare = compare_class_metadata
end

module UpdateResult = Environment.UpdateResult.Make (PreviousEnvironment)

let produce_class_metadata { class_hierarchy_environment } class_name ~track_dependencies =
  let unannotated_global_environment_dependency =
    Option.some_if track_dependencies (SharedMemoryKeys.RegisterClassMetadata class_name)
  in
  let alias_environment =
    ClassHierarchyEnvironment.ReadOnly.alias_environment class_hierarchy_environment
  in
  let unannotated_global_environment =
    alias_environment |> AliasEnvironment.ReadOnly.unannotated_global_environment
  in
  let add definition =
    let successors annotation =
      let linearization =
        let dependency =
          Option.some_if track_dependencies (SharedMemoryKeys.RegisterClassMetadata class_name)
        in
        ClassHierarchy.method_resolution_order_linearize
          ~get_successors:
            (ClassHierarchyEnvironment.ReadOnly.get_edges class_hierarchy_environment ?dependency)
          annotation
      in
      match linearization with
      | _ :: successors -> successors
      | [] -> []
    in
    let ast_environment =
      unannotated_global_environment |> UnannotatedGlobalEnvironment.ReadOnly.ast_environment
    in
    let successors = successors class_name in
    let is_final =
      definition |> fun { Node.value = definition; _ } -> ClassSummary.is_final definition
    in
    let in_test =
      let is_unit_test { Node.value = definition; _ } = ClassSummary.is_unit_test definition in
      let successor_classes =
        List.filter_map
          ~f:
            (UnannotatedGlobalEnvironment.ReadOnly.get_class_definition
               ?dependency:unannotated_global_environment_dependency
               unannotated_global_environment)
          successors
      in
      List.exists ~f:is_unit_test successor_classes
    in
    let extends_placeholder_stub_class =
      let dependency =
        Option.some_if track_dependencies (SharedMemoryKeys.RegisterClassMetadata class_name)
      in
      definition
      |> AnnotatedBases.extends_placeholder_stub_class
           ~aliases:(AliasEnvironment.ReadOnly.get_alias alias_environment ?dependency)
           ~from_empty_stub:(AstEnvironment.ReadOnly.from_empty_stub ast_environment ?dependency)
    in
    { is_test = in_test; successors; is_final; extends_placeholder_stub_class }
  in
  UnannotatedGlobalEnvironment.ReadOnly.get_class_definition
    unannotated_global_environment
    class_name
    ?dependency:unannotated_global_environment_dependency
  >>| add


module MetadataTable = Environment.EnvironmentTable.WithCache (struct
  module PreviousEnvironment = PreviousEnvironment
  module UpdateResult = UpdateResult
  module Key = SharedMemoryKeys.StringKey
  module Value = ClassMetadataValue

  type nonrec t = t

  type trigger = string

  let convert_trigger = Fn.id

  module TriggerSet = Type.Primitive.Set

  let produce_value = produce_class_metadata

  let filter_upstream_dependency = function
    | SharedMemoryKeys.RegisterClassMetadata name -> Some name
    | _ -> None


  let added_keys upstream_update =
    ClassHierarchyEnvironment.UpdateResult.upstream upstream_update
    |> AliasEnvironment.UpdateResult.upstream
    |> UnannotatedGlobalEnvironment.UpdateResult.added_classes


  let current_and_previous_keys upstream_update =
    ClassHierarchyEnvironment.UpdateResult.upstream upstream_update
    |> AliasEnvironment.UpdateResult.upstream
    |> UnannotatedGlobalEnvironment.UpdateResult.current_classes_and_removed_classes


  let all_keys class_hierarchy_environment =
    ClassHierarchyEnvironment.ReadOnly.alias_environment class_hierarchy_environment
    |> AliasEnvironment.ReadOnly.unannotated_global_environment
    |> UnannotatedGlobalEnvironment.ReadOnly.all_classes


  let serialize_value { successors; is_test; is_final; extends_placeholder_stub_class } =
    `Assoc
      [
        "successors", `String (List.to_string ~f:Type.Primitive.show successors);
        "is_test", `Bool is_test;
        "is_final", `Bool is_final;
        "extends_placeholder_stub_class", `Bool extends_placeholder_stub_class;
      ]
    |> Yojson.to_string


  let show_key = Fn.id

  let equal_value = equal_class_metadata
end)

let update = MetadataTable.update

let read_only { class_hierarchy_environment } = MetadataTable.read_only class_hierarchy_environment

module ReadOnly = struct
  include MetadataTable.ReadOnly

  let get_class_metadata = get

  let class_hierarchy_environment = upstream_environment
end

module MetadataReadOnly = ReadOnly
