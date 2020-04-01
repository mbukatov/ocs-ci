import copy
import logging
import textwrap

import pytest

from ocs_ci.ocs import constants, ocp
from ocs_ci.ocs.resources.objectconfigfile import ObjectConfFile
from ocs_ci.ocs.resources.pod import Pod
from tests import helpers

log = logging.getLogger(__name__)


def create_fio_pod(
    project,
    interface,
    pvc_factory,
    storageclass,
    access_mode,
    fio_job_dict,
    fio_configmap_dict,
    tmp_path,
    volume_mode=None,
    pvc_size=10
):
    """
    Create pods for upgrade testing.

    Args:
        project (obj): Project in which to create resources
        interface (str): CephBlockPool or CephFileSystem
        pvc_factory (function): Function for creating PVCs
        storageclass (obj): Storageclass to use
        access_mode (str): ReadWriteOnce, ReadOnlyMany or ReadWriteMany.
            This decides the access mode to be used for the PVC
        fio_job_dict (dict): fio job dictionary to use
        fio_configmap_dict (dict): fio configmap dictionary to use
        tmp_path (obj): reference to tmp_path fixture object
        volume_mode (str): Volume mode for rbd RWO PVC
        pvc_size (int): Size of PVC in GiB

    Return:
        list: List of generated pods

    """
    log.info(
        f"Creating pod via {interface} using {access_mode}"
        f" access mode, {volume_mode} volume mode and {storageclass.name}"
        f" storageclass"
    )
    pvc = pvc_factory(
        project=project,
        storageclass=storageclass,
        access_mode=access_mode,
        volume_mode=volume_mode,
        size=pvc_size,
        status=None
    )
    helpers.wait_for_resource_state(
        pvc,
        constants.STATUS_BOUND,
        timeout=600
    )

    fio_job_dict['spec']['template']['spec']['volumes'][0][
        'persistentVolumeClaim'
    ]['claimName'] = pvc.name
    fio_objs = [fio_configmap_dict, fio_job_dict]
    job_file = ObjectConfFile(
        "fio_continuous",
        fio_objs,
        project,
        tmp_path
    )

    # deploy the Job to the cluster and start it
    job_file.create()

    ocp_pod_obj = ocp.OCP(kind=constants.POD, namespace=project.namespace)
    pods = ocp_pod_obj.get()['items']
    for pod in pods:
        if pod['spec']['volumes'][0]['persistentVolumeClaim'][
            'claimName'
        ] == pvc.name:
            pod_data = pod
            break

    return Pod(**pod_data)


def set_fio_dicts(job_name, fio_job_dict, fio_configmap_dict, mode='fs'):
    """
    Set correct names for jobs, targets, configs and volumes in fio
    dictionaries.

    Args:
        job_name (str): fio job name
        fio_job_dict (dict): instance of fio_job_dict fixture
        fio_configmap_dict (dict): instance of fio_configmap_dict fixture
        mode (str): block or fs

    Returns:
        tupple: Edited fio_job_dict and fio_configmap_dict

    """
    config_name = f"{job_name}-config"
    volume_name = f"{config_name}-vol"
    target_name = f"{job_name}-target"

    fio_configmap_dict['metadata']['name'] = config_name
    fio_job_dict['metadata']['name'] = job_name
    fio_job_dict['spec']['template']['metadata']['name'] = job_name

    fio_job_dict['spec']['template']['spec']['volumes'][0][
        'name'
    ] = target_name
    fio_job_dict['spec']['template']['spec']['volumes'][0][
        'persistentVolumeClaim'
    ]['claimName'] = target_name
    fio_job_dict['spec']['template']['spec']['volumes'][1][
        'name'
    ] = volume_name
    fio_job_dict['spec']['template']['spec']['volumes'][1][
        'configMap'
    ]['name'] = config_name

    fio_job_dict['spec']['template']['spec']['containers'][0][
        'volumeMounts'
    ][0]['name'] = target_name
    fio_job_dict['spec']['template']['spec']['containers'][0][
        'volumeMounts'
    ][1]['name'] = volume_name

    if mode == 'block':
        # set correct path for fio volumes
        fio_job_dict_block = copy.deepcopy(fio_job_dict)
        job_spec = fio_job_dict_block['spec']['template']['spec']
        job_spec['containers'][0]['volumeDevices'] = []
        job_spec['containers'][0]['volumeDevices'].append(
            job_spec['containers'][0]['volumeMounts'].pop(0)
        )
        block_path = '/dev/rbdblock'
        # set correct path for fio volumes
        job_spec[
            'containers'
        ][0]['volumeDevices'][0]['devicePath'] = block_path
        try:
            job_spec['containers'][0]['volumeDevices'][0].pop('mountPath')
        except:
            pass
        return fio_job_dict_block, fio_configmap_dict

    return fio_job_dict, fio_configmap_dict


@pytest.fixture(scope='session')
def tmp_path(tmp_path_factory):
    """
    Path for fio related artefacts

    """
    return tmp_path_factory.mktemp('fio')


@pytest.fixture(scope='session')
def fio_project(project_factory_session):
    log.info('Creating project for fio jobs')
    return project_factory_session()


@pytest.fixture(scope='session')
def fio_conf_fs():
    """
    Basic fio configuration for upgrade utilization for fs based pvcs

    """
    # TODO(fbalak): handle better fio size
    fio_size = 1
    return textwrap.dedent(f"""
        [readwrite]
        readwrite=randrw
        buffered=1
        blocksize=4k
        ioengine=libaio
        directory=/mnt/target
        size={fio_size}G
        time_based
        runtime=24h
        numjobs=10
        """)


@pytest.fixture(scope='session')
def fio_conf_block():
    """
    Basic fio configuration for upgrade utilization for block based pvcs

    """
    # TODO(fbalak): handle better fio size
    fio_size = 1
    return textwrap.dedent(f"""
        [readwrite]
        readwrite=randrw
        buffered=1
        blocksize=4k
        ioengine=libaio
        directory=/dev/rbdblock
        size={fio_size}G
        time_based
        runtime=24h
        numjobs=10
        """)


@pytest.fixture(scope='session')
def pre_upgrade_filesystem_pods(
    request,
    pvc_factory_session,
    default_storageclasses,
    fio_job_dict,
    fio_configmap_dict,
    fio_conf_fs,
    fio_project,
    tmp_path
):
    """
    Generate RBD and CephFS pods for tests before upgrade is executed.
    These pods use filesystem volume type.

    Returns:
        list: List of pods with RBD and CephFs interface

    """
    pods = []
    pvc_size = 10
    fio_configmap_dict["data"]["workload.fio"] = fio_conf_fs

    for reclaim_policy in (
        constants.RECLAIM_POLICY_DELETE,
        constants.RECLAIM_POLICY_RETAIN
    ):
        job_name = f"{reclaim_policy}-rbd-rwo-fs".lower()
        fio_job_dict, fio_configmap_dict = set_fio_dicts(
            job_name,
            fio_job_dict,
            fio_configmap_dict
        )
        rbd_pod = create_fio_pod(
            project=fio_project,
            interface=constants.CEPHBLOCKPOOL,
            pvc_factory=pvc_factory_session,
            storageclass=default_storageclasses.get(reclaim_policy)[0],
            access_mode=constants.ACCESS_MODE_RWO,
            volume_mode=constants.VOLUME_MODE_FILESYSTEM,
            fio_job_dict=fio_job_dict,
            fio_configmap_dict=fio_configmap_dict,
            pvc_size=pvc_size,
            tmp_path=tmp_path
        )
        pods.append(rbd_pod)

        for access_mode in (
            constants.ACCESS_MODE_RWO,
            constants.ACCESS_MODE_RWX
        ):
            job_name = f"{reclaim_policy}-cephfs-{access_mode}-fs".lower()
            fio_job_dict, fio_configmap_dict = set_fio_dicts(
                job_name,
                fio_job_dict,
                fio_configmap_dict
            )
            cephfs_pod = create_fio_pod(
                project=fio_project,
                interface=constants.CEPHFILESYSTEM,
                pvc_factory=pvc_factory_session,
                storageclass=default_storageclasses.get(reclaim_policy)[1],
                access_mode=access_mode,
                fio_job_dict=fio_job_dict,
                fio_configmap_dict=fio_configmap_dict,
                pvc_size=pvc_size,
                tmp_path=tmp_path
            )
            pods.append(cephfs_pod)

    def teardown():
        for pod in pods:
            pod.delete()
    request.addfinalizer(teardown)

    return pods


@pytest.fixture(scope='session')
def pre_upgrade_block_pods(
    request,
    pvc_factory_session,
    default_storageclasses,
    fio_job_dict,
    fio_configmap_dict,
    fio_conf_block,
    fio_project,
    tmp_path
):
    """
    Generate RBD pods for tests before upgrade is executed.
    These pods use block volume type.

    Returns:
        list: List of pods with RBD interface

    """
    pods = []

    pvc_size = 10
    fio_configmap_dict["data"]["workload.fio"] = fio_conf_block

    for reclaim_policy in (
        constants.RECLAIM_POLICY_DELETE,
        constants.RECLAIM_POLICY_RETAIN
    ):
        for access_mode in (
            constants.ACCESS_MODE_RWX,
            constants.ACCESS_MODE_RWO
        ):
            job_name = f"{reclaim_policy}-rbd-{access_mode}-block".lower()
            fio_job_dict_block, fio_configmap_dict = set_fio_dicts(
                job_name,
                fio_job_dict,
                fio_configmap_dict,
                mode='block'
            )

            rbd_pod = create_fio_pod(
                project=fio_project,
                interface=constants.CEPHBLOCKPOOL,
                pvc_factory=pvc_factory_session,
                storageclass=default_storageclasses.get(reclaim_policy)[0],
                access_mode=access_mode,
                volume_mode=constants.VOLUME_MODE_BLOCK,
                fio_job_dict=fio_job_dict_block,
                fio_configmap_dict=fio_configmap_dict,
                pvc_size=pvc_size,
                tmp_path=tmp_path
            )
            pods.append(rbd_pod)

    def teardown():
        for pod in pods:
            pod.delete()
    request.addfinalizer(teardown)

    return pods


@pytest.fixture
def post_upgrade_filesystem_pods(
    pvc_factory,
    default_storageclasses,
    fio_job_dict,
    fio_configmap_dict,
    fio_conf_fs,
    fio_project,
    tmp_path
):
    """
    Generate RBD and CephFS pods for tests after upgrade is executed.
    These pods use filesystem volume type.

    Returns:
        list: List of pods with RBD and CephFS interface

    """
    pods = []

    pvc_size = 10
    fio_configmap_dict["data"]["workload.fio"] = fio_conf_fs

    for reclaim_policy in (
        constants.RECLAIM_POLICY_DELETE,
        constants.RECLAIM_POLICY_RETAIN
    ):
        job_name = f"{reclaim_policy}-rbd-rwo-fs-post".lower()
        fio_job_dict, fio_configmap_dict = set_fio_dicts(
            job_name,
            fio_job_dict,
            fio_configmap_dict
        )
        rbd_pod = create_fio_pod(
            project=fio_project,
            interface=constants.CEPHBLOCKPOOL,
            pvc_factory=pvc_factory,
            storageclass=default_storageclasses.get(reclaim_policy)[0],
            access_mode=constants.ACCESS_MODE_RWO,
            volume_mode=constants.VOLUME_MODE_FILESYSTEM,
            fio_job_dict=fio_job_dict,
            fio_configmap_dict=fio_configmap_dict,
            pvc_size=pvc_size,
            tmp_path=tmp_path

        )
        pods.append(rbd_pod)

        for access_mode in (
            constants.ACCESS_MODE_RWO,
            constants.ACCESS_MODE_RWX
        ):
            job_name = f"{reclaim_policy}-cephfs-{access_mode}-fs-post".lower()
            fio_job_dict, fio_configmap_dict = set_fio_dicts(
                job_name,
                fio_job_dict,
                fio_configmap_dict
            )
            cephfs_pod = create_fio_pod(
                project=fio_project,
                interface=constants.CEPHFILESYSTEM,
                pvc_factory=pvc_factory,
                storageclass=default_storageclasses.get(reclaim_policy)[1],
                access_mode=access_mode,
                fio_job_dict=fio_job_dict,
                fio_configmap_dict=fio_configmap_dict,
                pvc_size=pvc_size,
                tmp_path=tmp_path

            )
            pods.append(cephfs_pod)

    def teardown():
        for pod in pods:
            pod.delete()
    request.addfinalizer(teardown)

    return pods


@pytest.fixture
def post_upgrade_block_pods(
    pvc_factory,
    default_storageclasses,
    fio_job_dict,
    fio_configmap_dict,
    fio_conf_block,
    fio_project,
    tmp_path
):
    """
    Generate RBD pods for tests after upgrade is executed.
    These pods use block volume type.

    Returns:
        list: List of pods with RBD interface

    """
    pods = []

    pvc_size = 10
    fio_configmap_dict["data"]["workload.fio"] = fio_conf_block

    for reclaim_policy in (
        constants.RECLAIM_POLICY_DELETE,
        constants.RECLAIM_POLICY_RETAIN
    ):
        for access_mode in (
            constants.ACCESS_MODE_RWX,
            constants.ACCESS_MODE_RWO
        ):
            job_name = f"{reclaim_policy}-rbd-{access_mode}-fs-post".lower()
            fio_job_dict_block, fio_configmap_dict = set_fio_dicts(
                job_name,
                fio_job_dict,
                fio_configmap_dict,
                mode='block'
            )

            rbd_pod = create_fio_pod(
                project=fio_project,
                interface=constants.CEPHBLOCKPOOL,
                pvc_factory=pvc_factory,
                storageclass=default_storageclasses.get(reclaim_policy)[0],
                access_mode=access_mode,
                volume_mode=constants.VOLUME_MODE_BLOCK,
                fio_job_dict=fio_job_dict_block,
                fio_configmap_dict=fio_configmap_dict,
                pvc_size=pvc_size,
                tmp_path=tmp_path
            )
            pods.append(rbd_pod)

    def teardown():
        for pod in pods:
            pod.delete()
    request.addfinalizer(teardown)

    return pods


@pytest.fixture(scope='session')
def pre_upgrade_pods_running_io(
    pre_upgrade_filesystem_pods,
    pre_upgrade_block_pods,
):
    return pre_upgrade_filesystem_pods + pre_upgrade_block_pods
