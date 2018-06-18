#!/usr/bin/env python3.6

import sys
import os
import platform
import re
import subprocess

import zedenv.lib.be
import pyzfscmds.system.agnostic
import pyzfscmds.utility

from typing import List, Optional


def source(file: str):
    """
    'sources' a file and manipulates environment variables
    """

    env_command = ['sh', '-c', f'set -a && . {file} && env']

    try:
        env_output = subprocess.check_output(
            env_command, universal_newlines=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to gsource{file}.\n{e}\n.")

    for line in env_output.splitlines():
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


def grub_command(command: str, call_args: List[str] = None):

    cmd_call = [command]
    if call_args:
        cmd_call.extend(call_args)

    try:
        cmd_output = subprocess.check_output(
            cmd_call, universal_newlines=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to run {command}.\n{e}\n.")

    return cmd_output.splitlines()


class GrubLinuxEntry:

    def __init__(self, linux, be_root, rpool, genkernel_arch):
        self.linux = linux
        self.genkernel_arch = genkernel_arch
        self.basename = os.path.basename(linux)
        self.dirname = os.path.dirname(linux)
        try:
            self.rel_dirname = grub_command("grub-mkrelpath", [self.dirname])
        except RuntimeError as e:
            sys.exit(e)
        self.version = self.get_linux_version()

        self.rpool = rpool
        self.be_root = be_root
        self.boot_environment = self.get_boot_environment()

        self.linux_root_dataset = os.path.join(
            f"{self.rpool}{self.be_root}", self.boot_environment)
        self.linux_root_device = f"ZFS={self.linux_root_dataset}"

        self.initrd_early = self.get_initrd_early()
        self.initrd_real = self.get_initrd_real()
        self.initrd = self.get_initrd()

        self.kernel_config = self.get_kernel_config()

    def get_kernel_config(self) -> Optional[str]:
        configs = [f"{self.dirname}/config-{self.version}",
                   f"/etc/kernels/kernel-config-{self.version}"]
        return next((c for c in configs if os.path.isfile(c)), None)

    def get_initrd(self) -> list:
        initrd = []
        if self.initrd_real:
            initrd.append(self.initrd_real)

        if self.initrd_early:
            initrd.extend(self.initrd_early)

        return initrd

    def get_initrd_early(self) -> list:
        """
        Get microcode images
        https://www.mail-archive.com/grub-devel@gnu.org/msg26775.html
        See grub-mkconfig for code
        GRUB_EARLY_INITRD_LINUX_STOCK is distro provided microcode, ie:
          intel-uc.img intel-ucode.img amd-uc.img amd-ucode.img
          early_ucode.cpio microcode.cpio"
        GRUB_EARLY_INITRD_LINUX_CUSTOM is for your custom created images
        """
        early_initrd = []
        if "GRUB_EARLY_INITRD_LINUX_STOCK" in os.environ:
            early_initrd.extend(os.environ['GRUB_EARLY_INITRD_LINUX_STOCK'].split())

        if "GRUB_EARLY_INITRD_LINUX_CUSTOM" in os.environ:
            early_initrd.extend(os.environ['GRUB_EARLY_INITRD_LINUX_CUSTOM'].split())

        return [i for i in early_initrd if os.path.isfile(os.path.join(self.dirname, i))]

    def get_initrd_real(self) -> Optional[str]:
        initrd_list = [f"initrd.img-{self.version}",
                       f"initrd-{self.version}.img",
                       f"initrd-{self.version}.gz",
                       f"initrd-{self.version}",
                       f"initramfs-{self.version}.img",
                       f"initramfs-genkernel-{self.version}"
                       f"initramfs-genkernel-{self.genkernel_arch}-{self.version}"]

        return next(
            (i for i in initrd_list if os.path.isfile(os.path.join(self.dirname, i))), None)

    def get_boot_environment(self):
        """
        Get name of BE from kernel directory
        """
        target = re.search(r'zedenv-(.*)/*$', self.dirname)
        if target:
            return target.group(1)
        return None

    def get_linux_version(self):
        """
        Gets the version after kernel, if there is one
        Example:
             vmlinuz-4.16.12_1 gives vmlinuz
        """
        target = re.search(r'^[^0-9]*-(.*)', self.basename)
        if target:
            return target.group(1)
        return ""


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
        source("/etc/default/grub")

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

        self.root_dataset = pyzfscmds.system.agnostic.mountpoint_dataset("/")
        self.be_root = zedenv.lib.be.root()

        # in GRUB terms, bootfs is everything after pool
        self.bootfs = "/" + self.root_dataset.split("/", 1)[1]
        self.rpool = self.root_dataset.split("/")[0]
        self.linux_root_device=f"ZFS={self.rpool}{self.bootfs}"

        self.machine = platform.machine()

        self.invalid_filenames = ["readme"]  # Normalized to lowercase
        self.invalid_extensions = [".dpkg", ".rpmsave", ".rpmnew", ".pacsave", ".pacnew"]

        self.boot_list = self.get_boot_list()

        self.genkernel_arch = self.get_genkernel_arch()

        self.linux_entries = []

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

    def get_boot_list(self, boot_path: str = "/boot"):
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
        """

        boot_list = []

        vmlinuz = r'(/vmlinuz-.*)'
        vmlinux = r'(/vmlinux-.*)'
        kernel = r'(/kernel-.*)'

        boot_entries = [os.path.join(boot_path, e) for e in os.listdir(boot_path)]
        boot_entries.extend([os.path.join(boot_path, e) for e in os.listdir("/")])

        boot_search = f"{boot_path}{vmlinuz}|{boot_path}{kernel}|{vmlinuz}"

        if re.search(r'(i[36]86)|x86_64', self.machine):
            boot_regex = re.compile(boot_search)
        else:
            boot_search = f"{boot_search}|{boot_path}{vmlinux}|{vmlinux}"
            boot_regex = re.compile(boot_search)

        for i in boot_entries:
            if boot_regex.search(i) and self.file_valid(i):
                boot_list.append(i)

        return boot_list

    def get_genkernel_arch(self):

        if re.search(r'i[36]86', self.machine):
            return "x86"

        if re.search(r'mips|mips64', self.machine):
            return "mips"

        if re.search(r'mipsel|mips64el', self.machine):
            return "mipsel"

        if re.search(r'arm.*', self.machine):
            return "arm"

        return self.machine

    def generate_grub_entries(self):
        for i in self.boot_list:
            self.linux_entries.append(GrubLinuxEntry(i, self.be_root, self.rpool))


#grub = Generator()
#print(grub.boot_list)
# print(grub.genkernel_arch)
