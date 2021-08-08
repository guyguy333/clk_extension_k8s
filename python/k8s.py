#!/usr/bin/env python3
# -*- coding:utf-8 -*-

import os
import subprocess
import grp
import json
import re
import sys
import time
from pathlib import Path
from shlex import split

import click

from click_project.decorators import (
    argument,
    group,
    option,
    flag,
    param_config,
)
from click_project.lib import (
    call,
    makedirs,
    move,
    download,
    extract,
    read,
    tempdir,
    temporary_file,
    cd,
    check_output,
    updated_env,
    which,
    get_keyring,
)
from click_project.log import get_logger
from click_project.config import config

LOGGER = get_logger(__name__)


class KubeCtl:
    def __init__(self):
        self.context = None

    def call(self, arguments):
        call(['kubectl', '--context', self.context] + arguments)

    def output(self, arguments):
        return check_output(['kubectl', '--context', self.context] + arguments)


@group()
@param_config('kubectl', '--context', '-c', typ=KubeCtl, help="The kubectl context to use", default='kind-kind')
def k8s():
    """Manipulate k8s"""


bin_dir = Path('~/.local/bin').expanduser()
kind_url = 'https://kind.sigs.k8s.io/dl/v0.11.1/kind-linux-amd64'
helm_url = 'https://get.helm.sh/helm-v3.6.0-linux-amd64.tar.gz'
kubectl_url = 'https://dl.k8s.io/release/v1.21.2/bin/linux/amd64/kubectl'
tilt_url = 'https://github.com/tilt-dev/tilt/releases/download/v0.22.3/tilt.0.22.3.linux.x86_64.tar.gz'
kind_config = """
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: kind
kubeadmConfigPatches:
- |
  apiVersion: kubeadm.k8s.io/v1beta2
  kind: ClusterConfiguration
  metadata:
    name: config
  apiServer:
    extraArgs:
      "feature-gates": "EphemeralContainers=true"
  scheduler:
    extraArgs:
      "feature-gates": "EphemeralContainers=true"
  controllerManager:
    extraArgs:
      "feature-gates": "EphemeralContainers=true"
- |
  apiVersion: kubeadm.k8s.io/v1beta2
  kind: InitConfiguration
  metadata:
    name: config
  nodeRegistration:
    kubeletExtraArgs:
      "feature-gates": "EphemeralContainers=true"
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
"""

cluster_issuer = '''apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: local
spec:
  ca:
    secretName: ca-key-pair
'''


@k8s.command()
def doctor():
    """Check if you have everything needed to run the stack."""
    docker = which('docker')
    if docker is None:
        raise click.UsageError("You need to install docker")
    if sys.platform == 'linux':
        if 'docker' not in [grp.getgrgid(g).gr_name for g in os.getgroups()]:
            raise click.UsageError("You need to add the current user in the docker group")
    LOGGER.info("We did not find a reason to believe you will have trouble playing with the stack")


@k8s.group(default_command='all')
def install_dependency():
    """Install the dependencies needed to setup the stack"""
    # call(['sudo', 'apt', 'install', 'libnss-myhostname', 'docker.io'])


@install_dependency.command()
@flag('--force', help="Overwrite the existing binaries")
def kind(force):
    """Install kind"""
    kind_version = re.search('/(v[0-9.]+)/', kind_url).group(1)
    if not force and not which("kind"):
        force = True
        LOGGER.info("Could not find kind")
    if which("kind"):
        found_kind_version = re.match('kind (v[0-9.]+) .+', check_output(['kind', 'version'])).group(1)
    if not force and found_kind_version != kind_version:
        force = True
        LOGGER.info(f"Found an older version of kind ({found_kind_version}) than the requested one {kind_version}")
    if force:
        download(kind_url, outdir=bin_dir, outfilename='kind', mode=0o755)
    else:
        LOGGER.info("No need to install kind, force with --force")


@install_dependency.command()
@flag('--force', help="Overwrite the existing binaries")
def helm(force):
    """Install helm"""
    helm_version = re.search('helm-(v[0-9.]+)', helm_url).group(1)
    if not force and not which("helm"):
        force = True
        LOGGER.info("Could not find helm")
    if which("helm"):
        found_helm_version = re.search('Version:"(v[0-9.]+)"', check_output(['helm', 'version'])).group(1)
    if not force and found_helm_version != helm_version:
        force = True
        LOGGER.info(f"Found an older version of helm ({found_helm_version}) than the requested one {helm_version}")
    if force:
        with tempdir() as d:
            extract(helm_url, d)
            move(Path(d) / 'linux-amd64' / 'helm', bin_dir / 'helm')
            (bin_dir / 'helm').chmod(0o755)
    else:
        LOGGER.info("No need to install helm, force with --force")


@install_dependency.command()
@flag('--force', help="Overwrite the existing binaries")
def tilt(force):
    """Install tilt"""
    tilt_version = re.search('/(v[0-9.]+)/', tilt_url).group(1)
    if not force and not which("tilt"):
        force = True
        LOGGER.info("Could not find tilt")
    if which("tilt"):
        found_tilt_version = re.match('(v[0-9.]+)', check_output(['tilt', 'version'])).group(1)
    if not force and found_tilt_version != tilt_version:
        force = True
        LOGGER.info(f"Found an older version of tilt ({found_tilt_version}) than the requested one {tilt_version}")
    if force:
        with tempdir() as d:
            extract(tilt_url, d)
            move(Path(d) / 'tilt', bin_dir / 'tilt')
    else:
        LOGGER.info('No need to install tilt, force with --force')


@install_dependency.command()
@flag('--force', help="Overwrite the existing binaries")
def kubectl(force):
    """Install kubectl"""
    kubectl_version = re.search('/(v[0-9.]+)/', kubectl_url).group(1)
    if not force and not which("kubectl"):
        force = True
        LOGGER.info("Could not find kubectl")
    if which("kubectl"):
        found_kubectl_version = re.match('Client Version: .+ GitVersion:"(v[0-9.]+)"',
                                         check_output(['kubectl', 'version', '--client=true'])).group(1)
    if not force and found_kubectl_version != kubectl_version:
        force = True
        LOGGER.info(
            f"Found an older version of kubectl ({found_kubectl_version}) than the requested one {kubectl_version}")
    if force:
        download(kubectl_url, outdir=bin_dir, outfilename='kubectl', mode=0o755)
    else:
        LOGGER.info("No need to install kubectl, force with --force")


@install_dependency.command()
@flag('--force', help="Overwrite the existing binaries")
def _all(force):
    """Install all the dependencies"""
    ctx = click.get_current_context()
    ctx.invoke(kubectl, force=force)
    ctx.invoke(helm, force=force)
    ctx.invoke(tilt, force=force)
    ctx.invoke(kind, force=force)


@k8s.command(flowdepends=['k8s.create-cluster'])
@option('--registry-provider', type=click.Choice(['gitlab']), help="What registry provider to connect to")
@option('--username', help="The username of the provider registry")
@option('--password', help="The password of the provider registry")
def install_docker_registry_secret(registry_provider, username, password):
    """Install the credential to get access to the given registry provider."""
    registries = {
        'gitlab': {
            'secret-name': 'gitlab-registry',
            'server': 'registry.gitlab.com',
        }
    }
    if registry_provider:
        if not (username and password):
            if res := get_keyring().get_password('click-project', f'{registry_provider}-registry-auth'):
                username, password = json.loads(res)
        username = username or click.prompt('username', hide_input=True, default='', show_default=False)
        password = password or click.prompt('password', hide_input=True, default='', show_default=False)
        registry = registries[registry_provider]
        config.kubectl.call([
            'create', 'secret', 'docker-registry', registry['secret-name'],
            f'--docker-server={registry["server"]}',
            f'--docker-username={username}',
            f'--docker-password={password}',
        ])  # yapf: disable
    else:
        LOGGER.status("No registry provider given, doing nothing.")


@k8s.command(flowdepends=["k8s.install-dependency.all"])
@argument('name', default='kind', help="The name of the cluster to create")
@flag('--recreate', help="Recreate it if it already exists")
def create_cluster(name, recreate):
    """Create a kind cluster"""
    if name in check_output('kind get clusters'.split()).split('\n'):
        if recreate:
            call(['kind', 'delete', 'clusters', name])
        else:
            LOGGER.info(f"A cluster with the name {name} already exists. Nothing to do.")
            return

    import yaml
    with temporary_file() as f:
        f.write(kind_config.encode('utf8'))
        f.close()
        call(['kind', 'create', 'cluster', '--config', f.name])


@k8s.command(flowdepends=["k8s.create-cluster"])
def install_ingress():
    """Install a ingress"""
    call(["helm", "repo", "add", "ingress-nginx", "https://kubernetes.github.io/ingress-nginx"])
    config.kubectl.call(['apply', '-f',
        'https://raw.githubusercontent.com/kubernetes/ingress-nginx/master/deploy/static/provider/kind/deploy.yaml'
    ])
    success = False
    while not success:
        try:
            config.kubectl.call(['wait', '--namespace', 'ingress-nginx', '--for=condition=ready', 'pod',
              '--selector=app.kubernetes.io/component=controller', '--timeout=120s'])
            success = True
        except subprocess.CalledProcessError:
            time.sleep(5)


@k8s.command(flowdepends=["k8s.install-ingress"])
def install_cert_manager():
    """Install a certificate manager in the current cluster"""
    call(['helm', 'repo', 'add', 'jetstack', 'https://charts.jetstack.io'])
    call([
        'helm', '--kube-context', config.kubectl.context,
        'upgrade', '--install', '--create-namespace', '--wait', 'cert-manager', 'jetstack/cert-manager',
        '--namespace', 'cert-manager',
        '--version', 'v1.2.0',
        '--set', 'installCRDs=true',
        '--set', 'ingressShim.defaultIssuerName=local',
        '--set', 'ingressShim.defaultIssuerKind=ClusterIssuer',
    ])  # yapf: disable
    # generate a certificate authority for the cert-manager
    with tempdir() as d, cd(d):
        call(['openssl', 'genrsa', '-out', 'ca.key', '2048'])
        call([
            'openssl', 'req', '-x509', '-new', '-nodes',
            '-key', 'ca.key',
            '-subj', '/CN=localhost',
            '-days', '3650',
            '-reqexts', 'v3_req',
            '-extensions', 'v3_ca',
            '-out', 'ca.crt',
        ])  # yapf: disable
        ca_secret = config.kubectl.output([
            'create', 'secret', 'tls', 'ca-key-pair',
            '--cert=ca.crt',
            '--key=ca.key',
            '--namespace=cert-manager',
            '--dry-run=true',
            '-o', 'yaml',
        ])  # yapf: disable
    with temporary_file() as f:
        f.write(f'''{ca_secret}
---
{cluster_issuer}
'''.encode('utf8'))
        f.close()
        config.kubectl.call(['apply', '-n', 'cert-manager', '-f', f.name])


@k8s.command(flowdepends=['k8s.create-cluster'])
@argument('domain', help="The domain name to define")
@argument('ip', default='172.17.0.1', help="The IP address for this domain")
def add_domain(domain, ip):
    """Add a new domain entry in K8s dns"""
    import yaml

    coredns_conf = config.kubectl.output(['get', 'cm', 'coredns', '-n', 'kube-system', '-o', 'yaml'])
    coredns_conf = yaml.load(coredns_conf, Loader=yaml.FullLoader)
    top_level_domain = domain.split('.')[-1]
    data = '''
    hosts custom.hosts %s {
        # new hosts here
        fallthrough
    }
'''
    data = data % top_level_domain
    if not re.search('hosts custom.hosts', coredns_conf['data']['Corefile']):
        last_bracket_index = coredns_conf['data']['Corefile'].rindex('}')
        coredns_conf['data']['Corefile'] = coredns_conf['data']['Corefile'][0:last_bracket_index] + data + '\n}'
    if re.search('# new hosts here', coredns_conf['data']['Corefile']):
        data = f'{ip} {domain}'
        coredns_conf['data']['Corefile'] = re.sub(r'(# new hosts here)', f'\\1\n{data}\n', coredns_conf['data']['Corefile'])
        with temporary_file() as f:
            f.write(yaml.dump(coredns_conf).encode('utf8'))
            f.close()
            config.kubectl.call(['apply', '-n', 'kube-system', '-f', f.name])
            config.kubectl.call(['rollout', 'restart', '-n', 'kube-system', 'deployment/coredns'])


@k8s.flow_command(flowdepends=['k8s.install-cert-manager'])
def flow():
    """Run the full k8s setup flow"""


@k8s.command()
def remove():
    """Remove the k8s cluster"""
    call(['kind', 'delete', 'cluster'])


@k8s.command()
def ipython():
    import IPython

    dict_ = globals()
    dict_.update(locals())
    IPython.start_ipython(argv=[], user_ns=dict_)


@k8s.command()
@option('--force/--no-force', '-f', help="Force update")
@option('--touch', '-t', help="Touch this file or directory when update is complete")
@option('--experimental-oci/--no-experimental-oci', default=True, help="Activate experimental OCI feature")
@option('packages', '--package', '-p', multiple=True, help="Other helm dir to package and include in the dependencies")
@argument('path', default='.', required=False, help="Helm chart path")
def helm_dependency_update(path, force, touch, experimental_oci, packages):
    """Update helm dependencies"""
    import yaml
    ctx = click.get_current_context()
    chart = yaml.load(open(f'{path}/Chart.yaml'), Loader=yaml.FullLoader)
    if 'dependencies' in chart:
        update = force
        for dep in chart['dependencies']:
            name = f'{dep["name"]}-{dep["version"]}.tgz'
            if not os.path.exists(f'{path}/charts/{name}'):
                LOGGER.info(f'{name} is missing, updating')
                update = True
        if update:
            if experimental_oci:
                with updated_env(HELM_EXPERIMENTAL_OCI='1'):
                    call(['helm', 'dependency', 'update', path])
            else:
                call(['helm', 'dependency', 'update', path])
        for package in packages:
            ctx.invoke(helm_dependency_update, path=package, force=force, experimental_oci=experimental_oci)
            pp = os.path.abspath(package)
            with cd(f'{path}/charts'):
                call(['helm', 'package', pp])
        if update and touch:
            LOGGER.action(f"touching {touch}")
            os.utime(touch)


@k8s.command()
@option('--docker-login/--no-docker-login', '-d', help="Also log into docker")
@option('--helm-login/--no-helm-login', '-h', help="Also log into helm")
@option('--export-password', '-p', help="Export the passwords that directory, with the registry host as name")
@argument('secret', help="K8s secret to use")
def docker_credentials(docker_login, helm_login, secret, export_password):
    """Extract the docker credentials from a k8s secret"""
    creds = config.kubectl.output(
        ['get', 'secret', secret, '--template', '{{index .data ".dockerconfigjson" | base64decode }}'])
    creds = json.loads(creds)
    for registry, values in creds['auths'].items():
        if docker_login:
            check_output(['docker', 'login', registry, '-u', values['username'], '-p', values['password']])
        if helm_login:
            check_output(['helm', 'registry', 'login', registry, '-u', values['username'], '-p', values['password']])
    if export_password:
        makedirs(export_password)
    for registry, values in creds['auths'].items():
        f_path = f'{export_password}/{registry}'
        if not os.path.exists(f_path) or read(f_path) != values['password']:
            with open(f_path, 'w') as f:
                LOGGER.action(f'writing to {f_path}')
                f.write(values['password'])
    print(json.dumps(creds['auths']))
