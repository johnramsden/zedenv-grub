#!/usr/bin/env python3.6

import os
import platform
import subprocess

from typing import List

import pyzfscmds.utility
import pyzfscmds.system.agnostic
import zedenv.lib.be


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

        self.root_dataset = zedenv.lib.be.root()
        # in GRUB terms, bootfs is everything after pool
        self.bootfs = "/" + self.root_dataset.split("/", 1)[1]
        self.rpool = pyzfscmds.system.agnostic.mountpoint_dataset("/").split("/")[0]
        self.linux_root_device=f"ZFS={self.rpool}{self.bootfs}"

        self.machine = platform.machine()

        self.invalid_filenames = ["readme"]  # Normalized to lowercase
        self.invalid_extensions = [".dpkg", ".rpmsave", ".rpmnew", ".pacsave", ".pacnew"]

    def file_valid(self, file_path):
        """
        Run equivalent checks to grub_file_is_not_garbage() from grub-mkconfig_lib
        Check file is valid and not one of:
        *.dpkg - debian dpkg
        *.rpmsave | *.rpmnew
        README* | */README* - documentation
        """
        if not os.path.isfile(file_path):
            return False

        file = os.path.basename(file_path)
        _, ext = os.path.splitext(file)

        if ext in self.invalid_extensions:
            return False

        if next((True for f in self.invalid_filenames if f.lower() in file.lower()), False):
            return False

        return True

    def get_boot_list(self):
        """
        Check if grub list item shows up

        machine=`uname -m`
        case "x$machine" in
            xi?86 | xx86_64)
            list=
            for i in /boot/vmlinuz-* /vmlinuz-* /boot/kernel-* ; do
                if grub_file_is_not_garbage "$i" ; then list="$list $i" ; fi
            done ;;
            *)
            list=
            for i in /boot/vmlinuz-* /boot/vmlinux-* /vmlinuz-* /vmlinux-* /boot/kernel-* ; do
                          if grub_file_is_not_garbage "$i" ; then list="$list $i" ; fi
            done ;;
        esac

        case "$machine" in
            i?86) GENKERNEL_ARCH="x86" ;;
            mips|mips64) GENKERNEL_ARCH="mips" ;;
            mipsel|mips64el) GENKERNEL_ARCH="mipsel" ;;
            arm*) GENKERNEL_ARCH="arm" ;;
            *) GENKERNEL_ARCH="$machine" ;;
        esac
        """
        pass

    def grub_command(self, command: str, call_args: List[str] = None):

        cmd_call = [command]
        if call_args:
            cmd_call.extend(call_args)

        try:
            cmd_output = subprocess.check_output(
                cmd_call, universal_newlines=True, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to run {command}.\n{e}\n.")

        return cmd_output.splitlines()


grub = Generator()
