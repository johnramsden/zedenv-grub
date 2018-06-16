#!/usr/bin/env python3.6

import os
import subprocess


def source(file: str):
    """
    'sources' a file and manipulates environment variables
    """

    env_command = ['sh', '-c', f'set -a && . {file} && env']

    env_output = subprocess.Popen(env_command, stdout=subprocess.PIPE)

    for line in env_output.stdout:
        (key, _, value) = line.partition("=")
        os.environ[key] = value


def normalize_string(str_input: str):
    """
    Given a string, remove all non alphanumerics, and replace spaces with underscores
    """
    str_list = []
    for c in str_input.split(" "):
        san = [l.lower() for l in c if l.isalnum()]
        str_list.append("".join(san))

    return "_".join(str_list)


class Generator:

    def __init__(self):

        self.prefix = "/usr"
        self.exec_prefix = "/usr"
        self.data_root_dir = "/usr/share"

        if "pkgdatadir" in os.environ:
            self.pkgdatadir = os.environ['pkgdatadir']
        else:
            self.pkgdatadir = "/usr/share/grub"

        self.text_domain = "grub"
        self.text_domain_dir = f"{self.data_root_dir}/locale"

        # Update environment variables by sourcing grub defaults
        source("/etc/defaults/grub")

        grub_class = "--class gnu-linux --class gnu --class os"

        if "GRUB_DISTRIBUTOR" in os.environ:
            grub_distributor = os.environ['GRUB_DISTRIBUTOR']
            self.grub_os = f"{grub_distributor} GNU/Linux"
            self.grub_class = f"--class {normalize_string(grub_distributor)} {grub_class}"
        else:
            self.grub_os = "GNU/Linux"
            self.grub_class = grub_class

        # Default to true in order to maintian compatibility with older kernels.
        self.grub_disable_linux_partuuid = True
        if "GRUB_DISABLE_LINUX_PARTUUID" in os.environ:
            if os.environ['GRUB_DISABLE_LINUX_PARTUUID'] == ("false" or "False" or "0"):
                self.grub_disable_linux_partuuid = False
