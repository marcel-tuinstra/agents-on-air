"""Opt-in viewing from other devices on the local network.

Other devices enter a six-digit code once; the session cookie carries them
after that. This computer needs no code. A few wrong codes lock out new
devices until the server restarts with a fresh code.
"""
import ipaddress
import secrets
import socket
import subprocess
import sys
import threading

MAX_FAILURES = 10
LOOPBACK_NAMES = frozenset({'127.0.0.1', 'localhost'})


def host_name(value, port):
    """The lowercase name in a Host or Origin value, or None when the port differs."""
    name, separator, given = (value or '').rpartition(':')
    if not separator or given != str(port):
        return None
    return name.lower()


def is_ip_literal(name):
    # An address literal cannot be rebound by DNS, unlike a hostname.
    try:
        ipaddress.ip_address(name.strip('[]'))
        return True
    except ValueError:
        return False


def local_names():
    """Names this computer answers to on the network (Bonjour/mDNS and the plain hostname)."""
    hostname = socket.gethostname().lower()
    names = {hostname, hostname.split('.')[0] + '.local'}
    if sys.platform == 'darwin':
        try:
            bonjour = subprocess.run(['scutil', '--get', 'LocalHostName'], capture_output=True,
                                     text=True, timeout=2, check=True).stdout.strip()
            if bonjour:
                names.add(bonjour.lower() + '.local')
        except (OSError, subprocess.SubprocessError):
            pass
    return names


def local_addresses():
    """IPv4 addresses other devices can likely reach; best effort, for the startup message."""
    found = set()
    try:
        found.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    usable = sorted(a for a in found if not a.startswith(('127.', '169.254.')))
    if usable:
        return usable
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('192.0.2.1', 9))  # Sends nothing; only picks the outgoing interface.
            return [probe.getsockname()[0]]
    except OSError:
        return []


class LanAccess:
    def __init__(self, names=None, code=None):
        self.names = frozenset(LOOPBACK_NAMES | {n.lower() for n in (local_names() if names is None else names)})
        self.code = code or f'{secrets.randbelow(10 ** 6):06d}'
        self.failures = 0
        self.lock = threading.Lock()

    def host_allowed(self, name):
        return name in self.names or is_ip_literal(name)

    def locked(self):
        with self.lock:
            return self.failures >= MAX_FAILURES

    def check(self, code):
        # A six-digit code is guessable, so wrong tries count towards a lockout.
        with self.lock:
            if self.failures >= MAX_FAILURES:
                return False
            if secrets.compare_digest(code.encode(), self.code.encode()):
                return True
            self.failures += 1
            if self.failures == MAX_FAILURES:
                print('Too many wrong codes: new devices are locked out. Restart for a new code.', flush=True)
            return False

    def urls(self, port):
        names = sorted(n for n in self.names if n.endswith('.local'))
        return [f'http://{host}:{port}' for host in (*names, *local_addresses())]
