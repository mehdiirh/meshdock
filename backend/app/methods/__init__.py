"""Add adapters here; the API and UI discover their metadata through /methods."""

from .backhaul import Backhaul
from .frp import FrpWSS
from .gre import GRE
from .hysteria import Hysteria2
from .rathole import Rathole
from .reverse_ssh import ReverseSSH

REGISTRY = {
    m.metadata["id"]: m for m in (FrpWSS(), Hysteria2(), GRE(), Backhaul(), Rathole(), ReverseSSH())
}
