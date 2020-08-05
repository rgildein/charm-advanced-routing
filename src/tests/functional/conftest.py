#!/usr/bin/python3
"""
Reusable pytest fixtures for functional testing.

Environment variables
---------------------

test_preserve_model:
if set, the testing model won't be torn down at the end of the testing session
"""

import asyncio
import os
import subprocess
import uuid

import juju
from juju.controller import Controller
from juju.errors import JujuError

from juju_tools import JujuTools

import pytest


@pytest.fixture(scope="module")
def event_loop():
    """Override the default pytest event loop.

    Do this too allow for fixtures using a broader scope.
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_debug(True)
    yield loop
    loop.close()
    asyncio.set_event_loop(None)


@pytest.fixture(scope="module")
async def controller():
    """Connect to the current controller."""
    _controller = Controller()
    await _controller.connect_current()
    yield _controller
    await _controller.disconnect()


@pytest.fixture(scope="module")
async def model(controller):
    """Live only for the duration of the test."""
    model_name = "functest-{}".format(str(uuid.uuid4())[-12:])
    _model = await controller.add_model(
        model_name,
        cloud_name=os.getenv("PYTEST_CLOUD_NAME"),
        region=os.getenv("PYTEST_CLOUD_REGION"),
    )
    # https://github.com/juju/python-libjuju/issues/267
    subprocess.check_call(["juju", "models"])
    while model_name not in await controller.list_models():
        await asyncio.sleep(1)
    yield _model
    await _model.disconnect()
    if not os.getenv("PYTEST_KEEP_MODEL"):
        await controller.destroy_model(model_name)
        while model_name in await controller.list_models():
            await asyncio.sleep(1)


@pytest.fixture
async def get_unit(model):
    """Returns the requested <app_name>/<unit_number> unit."""

    async def _get_unit(name):
        try:
            (app_name, unit_number) = name.split("/")
            return model.applications[app_name].units[unit_number]
        except (KeyError, ValueError):
            raise JujuError("Cannot find unit {}".format(name))

    return _get_unit


@pytest.fixture
async def run_command(get_unit):
    """
    Runs a command on a unit.

    :param cmd: Command to be run
    :param target: Unit object or unit name string
    """

    async def _run_command(cmd, target):
        unit = target if type(target) is juju.unit.Unit else await get_unit(target)
        action = await unit.run(cmd)
        return action.results

    return _run_command


@pytest.fixture
async def get_app(model):
    """Returns the application by name in the model."""

    async def _get_app(name):
        try:
            return model.applications[name]
        except KeyError:
            raise JujuError("Cannot find application {}".format(name))

    return _get_app


@pytest.fixture
async def file_contents(run_command):
    """
    Returns the contents of a file.

    :param path: File path
    :param target: Unit object or unit name string
    """

    async def _file_contents(path, target):
        cmd = "cat {}".format(path)
        results = await run_command(cmd, target)
        return results["Stdout"]

    return _file_contents


@pytest.fixture
async def file_exists(run_command):
    """
    Returns 1 or 0 based on if file exists or not in target unit.

    :param path: File path
    :param target: Unit object or unit name string
    """

    async def _file_exists(path, target):
        cmd = '[ -f "{}" ] && echo 1 || echo 0'.format(path)
        results = await run_command(cmd, target)
        return results["Stdout"]

    return _file_exists


@pytest.fixture
async def reconfigure_app(get_app, model):
    """Applies a different config to the requested app."""

    async def _reconfigure_app(cfg, target):
        application = (
            target
            if type(target) is juju.application.Application
            else await get_app(target)
        )
        await application.set_config(cfg)
        await application.get_config()
        await model.block_until(lambda: application.status == "active")

    return _reconfigure_app


@pytest.fixture(scope="module")
async def jujutools(controller, model):
    """Juju tools."""
    tools = JujuTools(controller, model)
    return tools
