(* Copyright (c) 2016-present, Facebook, Inc.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree. *)

open Core

type 'node_type t = {
  location: Location.t; [@hash.ignore]
  value: 'node_type;
}
[@@deriving sexp, show, hash, to_yojson]

let create ~location value = { location; value }

let create_with_default_location value = { location = Location.Reference.any; value }

let pp print_node format { value; _ } = print_node format value

let compare compare_value left right = compare_value left.value right.value

let equal equal_value left right = equal_value left.value right.value

let location_sensitive_hash_fold hash_fold_value state { location; value } =
  let state = [%hash_fold: Location.t] state location in
  hash_fold_value state value


let location_sensitive_compare compare_value left right =
  match [%compare: Location.t] left.location right.location with
  | 0 -> compare_value left.value right.value
  | _ as result -> result


let start { location; _ } = location.Location.start

let stop { location; _ } = location.Location.stop

let value { value; _ } = value

let location { location; _ } = location

let map { location; value } ~f = { location; value = f value }
