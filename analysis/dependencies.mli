(* Copyright (c) 2016-present, Facebook, Inc.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree. *)

open Core
open Ast
module SharedMemory = Memory

type t

val create : AstEnvironment.ReadOnly.t -> t

val transitive_of_list : t -> modules:Reference.t list -> Reference.Set.t

val of_list : t -> modules:Reference.t list -> Reference.Set.t

val to_dot : t -> qualifier:Reference.t -> string

val register_all_dependencies : t -> Source.t list -> unit

val add_manual_dependency_for_test : t -> source:Reference.t -> target:Reference.t -> unit

val normalize : t -> Reference.t list -> unit

val purge : t -> Reference.t list -> unit

module Callgraph : sig
  type dispatch =
    | Dynamic
    | Static

  and callee =
    | Function of Reference.t
    | Method of {
        class_name: Type.t;
        direct_target: Reference.t;
        dispatch: dispatch;
        is_optional_class_attribute: bool;
      }
  [@@deriving compare, eq, show]

  type callee_with_locations = {
    callee: callee;
    locations: Location.Reference.t list;
  }

  val callee_to_yojson : ?locations:Location.Instantiated.t list -> callee -> Yojson.Safe.t

  include Hashable with type t := callee

  module CalleeValue : SharedMemory.ValueType with type t = callee_with_locations list

  module SharedMemory :
    Memory.WithCache.S
      with type t = CalleeValue.t
       and type key = SharedMemoryKeys.ReferenceKey.t
       and type key_out = SharedMemoryKeys.ReferenceKey.out
       and module KeySet = Caml.Set.Make(SharedMemoryKeys.ReferenceKey)
       and module KeyMap = MyMap.Make(SharedMemoryKeys.ReferenceKey)

  val set : caller:Reference.t -> callees:callee_with_locations list -> unit

  val get : caller:Reference.t -> callee_with_locations list

  module type Builder = sig
    val initialize : unit -> unit

    val add_callee
      :  global_resolution:GlobalResolution.t ->
      target:Type.t option ->
      callables:Type.Callable.t list option ->
      dynamic:bool ->
      callee:Ast.Expression.t ->
      unit

    val add_property_callees
      :  global_resolution:GlobalResolution.t ->
      resolved_base:Type.t ->
      attributes:(AnnotatedAttribute.t * Type.t) list ->
      name:string ->
      location:Ast.Location.Reference.t ->
      unit

    val get_all_callees : unit -> callee_with_locations list
  end

  module DefaultBuilder : Builder
end
