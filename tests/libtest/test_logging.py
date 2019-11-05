# -*- coding: utf8 -*-
import logging

import pytest

from ocs_ci.framework.testlib import ManageTest, libtest
from ocs_ci.ocs.ocp import OCP
from tests import helpers


log = logging.getLogger(__name__)


@libtest
class TestLogging(ManageTest):

    def test_wait_for_one(self):
        ocp = OCP(kind='pv')
        ocp.wait_for_resource(
            resource_name='pvc-000e69cf-c2b4-11e9-a6dc-0625533a766a',
            condition='Released')

    def test_wait_for_many(self):
        ocp = OCP(kind='pv')
        ocp.wait_for_resource(condition='Released', resource_count=10)

    def test_validate_pv_delete(self):
        helpers.validate_pv_delete("pvc-000e69cf-c2b4-11e9-a6dc-0625533a766a")
