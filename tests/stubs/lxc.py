"""
In-memory stand-in for python-lxc, so the API tests run without LXC (e.g. in CI):
    HABENY_LXC_BACKEND=direct PYTHONPATH=tests/stubs pytest
Containers "exist" only in this process and do nothing.
"""
version = "stub"
default_config_path = "/var/lib/lxc"

_containers = {}


def list_containers(active=True, defined=True, as_object=False, config_path=None):
    names = sorted(_containers)
    return [_containers[n] for n in names] if as_object else names


class Container:
    def __init__(self, name, config_path=None):
        self.name = name
        existing = _containers.get(name)
        self.defined = existing is not None
        self.running = existing.running if existing else False
        self.state = existing.state if existing else "STOPPED"
        self.init_pid = 1

    def create(self, template, flags=0, args=None):
        _containers[self.name] = self
        self.defined = True
        return True

    def start(self):
        self.running, self.state = True, "RUNNING"
        return True

    def stop(self):
        self.running, self.state = False, "STOPPED"
        return True

    def shutdown(self, timeout=-1):
        return self.stop()

    def destroy(self):
        _containers.pop(self.name, None)
        self.defined = False
        return True

    def wait(self, state, timeout=-1):
        return True

    def save_config(self):
        return True

    def get_ips(self, *args, **kwargs):
        return ("10.0.3.2",) if self.running else ()

    def get_interfaces(self):
        return ("lo", "eth0")

    def get_cgroup_item(self, key):
        return ""

    def set_cgroup_item(self, key, value):
        return True

    def set_config_item(self, key, value):
        return True

    def clear_config_item(self, key):
        return True
