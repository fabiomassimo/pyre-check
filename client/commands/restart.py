# Copyright (c) 2016-present, Facebook, Inc.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

# pyre-unsafe

import argparse
from typing import Optional

from ..analysis_directory import AnalysisDirectory, resolve_analysis_directory
from .command import Command, IncrementalStyle
from .incremental import Incremental
from .start import Start
from .stop import Stop


class Restart(Command):
    NAME = "restart"

    def __init__(
        self,
        arguments,
        configuration,
        analysis_directory: Optional[AnalysisDirectory] = None,
    ) -> None:
        super(Restart, self).__init__(arguments, configuration, analysis_directory)

    @classmethod
    def add_subparser(cls, parser: argparse._SubParsersAction) -> None:
        restart = parser.add_parser(
            cls.NAME,
            epilog="Restarts a server. Equivalent to `pyre stop && pyre start`.",
        )
        restart.set_defaults(command=cls)
        restart.add_argument(
            "--terminal", action="store_true", help="Run the server in the terminal."
        )
        restart.add_argument(
            "--store-type-check-resolution",
            action="store_true",
            help="Store extra information for `types` queries.",
        )
        restart.add_argument(
            "--no-watchman",
            action="store_true",
            help="Do not spawn a watchman client in the background.",
        )
        restart.add_argument(
            "--incremental-style",
            type=IncrementalStyle,
            choices=list(IncrementalStyle),
            default=IncrementalStyle.SHALLOW,
            help="How to approach doing incremental checks.",
        )

    def generate_analysis_directory(self) -> AnalysisDirectory:
        return resolve_analysis_directory(
            self._arguments, self._configuration, build=True
        )

    def _run(self) -> None:
        Stop(self._arguments, self._configuration, self._analysis_directory).run()
        # Force the incremental run to be blocking.
        # pyre-fixme[16]: `Namespace` has no attribute `nonblocking`.
        self._arguments.nonblocking = False
        Incremental(
            self._arguments, self._configuration, self._analysis_directory
        ).run()
