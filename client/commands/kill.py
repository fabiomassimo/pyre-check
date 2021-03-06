# Copyright (c) 2016-present, Facebook, Inc.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import argparse
import logging
import os
import shutil
import signal
import subprocess
from typing import Optional

import psutil

from .. import BINARY_NAME, CLIENT_NAME
from ..analysis_directory import AnalysisDirectory
from ..configuration import Configuration
from .command import Command


LOG = logging.getLogger(__name__)  # type: logging.Logger


class Kill(Command):
    NAME = "kill"

    def __init__(
        self,
        arguments: argparse.Namespace,
        configuration: Configuration,
        analysis_directory: Optional[AnalysisDirectory] = None,
    ) -> None:
        super(Kill, self).__init__(arguments, configuration, analysis_directory)

    @classmethod
    def add_subparser(cls, parser: argparse._SubParsersAction) -> None:
        kill = parser.add_parser(cls.NAME)
        kill.set_defaults(command=cls)
        kill.add_argument(
            "--with-fire", action="store_true", help="Adds emphasis to the command."
        )

    def generate_analysis_directory(self) -> AnalysisDirectory:
        return AnalysisDirectory(".")

    def _run(self) -> None:
        # Kills all processes that have the same binary as the one specified
        # in the configuration.
        binary_name = _get_process_name("PYRE_BINARY", BINARY_NAME)
        subprocess.run(["pkill", binary_name])
        server_root = os.path.join(self._log_directory, "server")

        def _delete_linked_path(link_path: str) -> None:
            try:
                actual_path = os.readlink(link_path)
                os.remove(actual_path)
            except OSError:
                pass
            try:
                os.unlink(link_path)
            except OSError:
                pass

        _delete_linked_path(os.path.join(server_root, "server.sock"))
        _delete_linked_path(os.path.join(server_root, "json_server.sock"))

        if self._arguments.with_fire is True:
            # If a resource cache exists, delete it to remove corrupted artifacts.
            try:
                shutil.rmtree(os.path.join(self._log_directory, "resource_cache"))
            except OSError:
                pass
            # If a buck builder cache exists, also remove it.
            try:
                shutil.rmtree("/tmp/pyre/buck_builder_cache")
            except OSError:
                pass

        for process in psutil.process_iter(attrs=["name"]):
            if process.info["name"] != CLIENT_NAME:
                continue
            # We need to be careful about how we kill the client here, as otherwise we
            # might cause a race where we attempt to kill the `pyre kill` command.
            pid_to_kill = process.pid
            if pid_to_kill == os.getpgid(os.getpid()):
                continue
            try:
                os.kill(pid_to_kill, signal.SIGKILL)
            except ProcessLookupError:
                continue


def _get_process_name(environment_variable_name: str, default: str) -> str:
    overridden = os.getenv(environment_variable_name)
    if overridden is not None:
        return os.path.basename(overridden)
    else:
        return default
