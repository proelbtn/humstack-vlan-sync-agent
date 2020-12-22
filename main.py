import ipaddress
import os
import time

import netmiko 
import requests
import yaml

import logging
from typing import *
import traceback

from dataclasses import dataclass
from fastcore.all import *
import sentry_sdk
from sentry_sdk import capture_message

L = logging.getLogger(__name__)


@dataclass
class Network:
    network_id: int
    vlan_id: int
    cidr_v4: str
    gateway_v4: Tuple[str, str] # address, subnet mask
    cidr_v6: str # it's defined but not used


class Importer:
    def __init__(self, baseurl: str):
        store_attr()

    def _build_url(self, path: str) -> str:
        return "%s/api%s" % (self.baseurl, path)

    def _get_groups(self) -> List[str]:
        url = self._build_url("/v0/groups")
        res = requests.get(url)
        L.debug(res.content)

        groups = []
        for group in res.json()["data"]["groups"]:
            groups.append(group["meta"]["id"])

        return groups

    def _get_namespaces(self, group: str) -> List[str]:
        url = self._build_url("/v0/groups/%s/namespaces" % group)
        res = requests.get(url)
        L.debug(res.content)

        namespaces = []
        for namespace in res.json()["data"]["namespaces"]:
            namespaces.append(namespace["meta"]["id"])

        return namespaces

    def _get_networks(self, group: str, namespace: str) -> List[Network]:
        url = self._build_url("/v0/groups/%s/namespaces/%s/networks" % (group, namespace))
        res = requests.get(url)
        L.debug(res.content)

        networks = []
        for network in res.json()["data"]["networks"]:
            if network["meta"]["annotations"].get("require-gateway") != "true":
                continue
            network_id = network["meta"]["id"]
            vlan_id = int(network["spec"]["template"]["spec"]["id"])
            cidr_v4 = network["spec"]["template"]["spec"]["ipv4CIDR"]
            cidr_v6 = network["spec"]["template"]["spec"]["ipv6CIDR"]
            net_v4 = ipaddress.IPv4Network(cidr_v4)
            gateway_v4 = (str(net_v4.broadcast_address - 1), str(net_v4.netmask))
            networks.append(Network(network_id, vlan_id, cidr_v4, gateway_v4, cidr_v6))

        return networks

    def poll(self) -> List[Network]:
        networks = []

        groups = self._get_groups()
        for group in groups:
            namespaces = self._get_namespaces(group)
            for namespace in namespaces:
                networks.extend(self._get_networks(group, namespace))

        return networks


class Cisco4948Exporter:
    @dataclass
    class State:
        vlan_id: int
        is_enabled: bool

    def __init__(self, host: str, username: str, password: str, secret: str):
        store_attr()

    def __str__(self) -> str:
        return "Cisco4948Exporter (host: %s)" % self.host

    def get_current_states(self, client: netmiko.ConnectHandler) -> List[State]:
        output = client.send_command("show interface summary")
        lines = output.split("\n")

        states = []
        for line in lines[11:]:
            is_enabled = line[0] == "*"
            interface_name = line[2:].split()[0]
            if interface_name[:4] != "Vlan":
                return states
            vlan_id = int(interface_name[4:])
            states.append(self.State(vlan_id, is_enabled))

        return states

    def delete_vlan_definition(self, client: netmiko.ConnectHandler, vlan_id: int) -> bool:
        L.info("delete_vlan_definition called (vlan_id: %d)" % vlan_id)
        commands = [
            "no interface vlan %d" % vlan_id
        ]
        client.send_config_set(commands)
        return True 

    def update_vlan_definition(self, client: netmiko.ConnectHandler, network: Network) -> bool:
        L.info("update_vlan_definition called (network: %s)" % network)
        commands = [
            "interface vlan %d" % network.vlan_id,
            "description %s" % network.network_id,
            "ip address %s %s" % network.gateway_v4,
            "no shutdown"
        ]
        client.send_config_set(commands)
        return True 

    def sync(self, networks: List[Network]) -> bool:
        client = netmiko.ConnectHandler(
                device_type="cisco_ios",
                host=self.host,
                username=self.username,
                password=self.password,
                secret=self.secret)
        client.enable()

        states = self.get_current_states(client)

        current_vlan_ids = { s.vlan_id: s.is_enabled for s in states }
        desired_vlan_ids = { n.vlan_id: n for n in networks }

        flag = False
        for v in current_vlan_ids:
            if v <= 100:
                continue
            if not v in desired_vlan_ids:
                is_deleted = self.delete_vlan_definition(client, v)
                flag |= is_deleted
    
        for v, n in desired_vlan_ids.items():
            if v <= 100:
                continue
            if not v in current_vlan_ids or not current_vlan_ids[v]:
                is_updated = self.update_vlan_definition(client, n)
                flag |= is_updated 

        client.cleanup()

        return flag


class VlanSyncAgent:
    def __init__(self, importer, exporters):
        store_attr()

    def run(self):
        L.info("starting VLAN Sync Agent")

        try:
            wait_sec = 5
            while True:
                networks = self.importer.poll()
                L.info("polling done: %s" % networks)

                for exporter in self.exporters:
                    L.info("syncing started (%s)" % exporter)
                    is_updated = exporter.sync(networks)
                    L.info("syncing done (%s, is_updated: %s)" % (exporter, is_updated))
            L.debug("sleeping %d secs..." % wait_sec)
            time.sleep(wait_sec)
        except Exception as e:
            L.error(traceback.format_exc())


def main():
    with open("config.yml", "r") as f:
        conf = f.read()
    conf = yaml.load(conf, Loader=yaml.SafeLoader)

    if "sentry" in conf:
        sentry_sdk.init(
            conf["sentry"]["endpoint"],
            conf["sentry"]["traces_sample_rate"],
        )

    logging.basicConfig(level=logging.INFO)
    importer = Importer(conf["importer"]["address"])

    exporters = []
    for exporter in conf["exporters"]:
        if exporter["type"] == "Cisco4948":
            exporters.append(Cisco4948Exporter(
                exporter["address"],
                exporter["username"],
                exporter["password"],
                exporter["secret"]))

    agent = VlanSyncAgent(importer, exporters)
    agent.run()


main()

