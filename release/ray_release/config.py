import copy
import datetime
import os
from typing import Any, Dict, List, Optional

import jinja2
import yaml

from ray_release.anyscale_util import find_cloud_by_name
from ray_release.exception import ReleaseTestConfigError
from ray_release.logger import logger
from ray_release.util import deep_update

Test = Dict[str, Any]

DEFAULT_WHEEL_WAIT_TIMEOUT = 1200
DEFAULT_COMMAND_TIMEOUT = 1800
DEFAULT_BUILD_TIMEOUT = 1800
DEFAULT_SESSION_TIMEOUT = 1800

DEFAULT_CLOUD_ID = "cld_4F7k8814aZzGG8TNUGPKnc"

DEFAULT_ENV = {
    "DATESTAMP": str(datetime.datetime.now().strftime("%Y%m%d")),
    "TIMESTAMP": str(int(datetime.datetime.now().timestamp())),
    "EXPIRATION_1D": str((datetime.datetime.now() +
                          datetime.timedelta(days=1)).strftime("%Y-%m-%d")),
    "EXPIRATION_2D": str((datetime.datetime.now() +
                          datetime.timedelta(days=2)).strftime("%Y-%m-%d")),
    "EXPIRATION_3D": str((datetime.datetime.now() +
                          datetime.timedelta(days=3)).strftime("%Y-%m-%d"))
}


class TestEnvironment(dict):
    pass


_test_env = None


def get_test_environment():
    global _test_env
    if _test_env:
        return _test_env

    _test_env = TestEnvironment(**DEFAULT_ENV)
    return _test_env


def set_test_env_var(key: str, value: str):
    test_env = get_test_environment()
    test_env[key] = value


def read_and_validate_release_test_collection(config_file: str) -> List[Test]:
    """Read and validate test collection from config file"""
    with open(config_file, "rt") as fp:
        test_config = yaml.safe_load(fp)

    validate_release_test_collection(test_config)
    return test_config


def validate_release_test_collection(test_collection: List[Dict[str, Any]]):
    errors = []
    for test in test_collection:
        errors += validate_test(test)

    if errors:
        raise ReleaseTestConfigError(
            f"Release test configuration error: Found {len(errors)} warnings.")


def validate_test(test: Test):
    # Todo: implement Schema validation
    return []


def find_test(test_collection: List[Test], test_name: str) -> Optional[Test]:
    """Find test with `test_name` in `test_collection`"""
    for test in test_collection:
        if test["name"] == test_name:
            return test
    return None


def as_smoke_test(test: Test) -> Test:
    if "smoke_test" not in test:
        logger.warning(
            f"Requested smoke test, but test with name {test['name']} does "
            f"not have any smoke test configuration.")
        return test

    smoke_test_config = test.pop("smoke_test")
    new_test = deep_update(test, smoke_test_config)
    return new_test


def get_wheels_sanity_check(commit: Optional[str] = None):
    if not commit:
        cmd = ("python -c 'import ray; print("
               "\"No commit sanity check available, but this is the "
               "Ray wheel commit:\", ray.__commit__)'")
    else:
        cmd = (f"python -c 'import ray; "
               f"assert ray.__commit__ == \"{commit}\", ray.__commit__'")
    return cmd


def load_and_render_yaml_template(
        template_path: str, env: Optional[Dict] = None) -> Optional[Dict]:
    if not template_path:
        return None

    if not os.path.exists(template_path):
        raise ReleaseTestConfigError(
            f"Cannot load yaml template from {template_path}: Path not found.")

    with open(template_path, "rt") as f:
        content = f.read()

    render_env = copy.deepcopy(os.environ)
    if env:
        render_env.update(env)

    content = jinja2.Template(content).render(env=env)
    return yaml.safe_load(content)


def load_test_cluster_env(test: Test, ray_wheels_url: str) -> Optional[Dict]:
    cluster_env_file = test["cluster"]["cluster_env"]
    env = get_test_environment()

    commit = env.get("commit", None)
    env["RAY_WHEELS_SANITY_CHECK"] = get_wheels_sanity_check(commit)
    env["RAY_WHEELS"] = ray_wheels_url

    return load_and_render_yaml_template(cluster_env_file, env=env)


def load_test_cluster_compute(test: Test) -> Optional[Dict]:
    cluster_compute_file = test["cluster"]["cluster_compute"]
    env = get_test_environment()

    cloud_id = get_test_cloud_id(test)
    env["ANYSCALE_CLOUD_ID"] = cloud_id

    return load_and_render_yaml_template(cluster_compute_file, env=env)


def get_test_cloud_id(test: Test) -> str:
    cloud_id = test["cluster"].get("cloud_id", None)
    cloud_name = test["cluster"].get("cloud_name", None)
    if cloud_id and cloud_name:
        raise RuntimeError(
            f"You can't supply both a `cloud_name` ({cloud_name}) and a "
            f"`cloud_id` ({cloud_id}) in the test cluster configuration. "
            f"Please provide only one.")
    elif cloud_name and not cloud_id:
        cloud_id = find_cloud_by_name(cloud_name)
        if not cloud_id:
            raise RuntimeError(
                f"Couldn't find cloud with name `{cloud_name}`.")
    else:
        cloud_id = cloud_id or DEFAULT_CLOUD_ID
    return cloud_id
