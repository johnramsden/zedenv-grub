import shutil
import os
import tempfile
import subprocess

import pyzfscmds.utility
import pyzfscmds.system.agnostic

import zedenv.cli.mount
import zedenv.lib.system
import zedenv.lib.be
import zedenv.plugins.configuration as plugin_config
from zedenv.lib.logger import ZELogger

from typing import Tuple


class GRUB(plugin_config.Plugin):
    systems_allowed = ["linux"]

    bootloader = "grub"

    allowed_properties: Tuple[dict] = (
        {
            "property": "boot",
            "description": "Set location for boot.",
            "default": "/mnt/boot"
        },
        {
            "property": "bootonzfs",
            "description": "Use ZFS for /boot.",
            "default": "yes"
        },
        {
            "property": "grubsubdir",
            "description": "Set name of subdirectory under boot.",
            "default": "grub"
        },
        {
            "property": "simpleentries",
            "description": "Add simple entries in GRUB.",
            "default": "yes"
        }
    )

    def __init__(self, zedenv_data: dict, skip_update: bool=False, skip_cleanup: bool=False):

        super().__init__(zedenv_data)

        self.entry_prefix = "zedenv"

        self.old_entry = f"{self.entry_prefix}-{self.old_boot_environment}"
        self.new_entry = f"{self.entry_prefix}-{self.boot_environment}"

        self.boot_mountpoint = "/boot"
        self.env_dir = "env"
        self.zfs_env_dir = "zfsenv"

        if not os.path.isdir(self.boot_mountpoint):
            ZELogger.log({
                "level": "EXCEPTION",
                "message": f"Boot mountpoint {self.boot_mountpoint} does not exist. Exiting.\n"
            }, exit_on_error=True)

        self.skip_update_grub = skip_update
        self.skip_cleanup = skip_cleanup

        # Set defaults
        for pr in self.allowed_properties:
            self.zedenv_properties[pr["property"]] = pr["default"]

        self.check_zedenv_properties()

        if self.zedenv_properties["bootonzfs"] == ("yes" or "1"):
            self.bootonzfs = True
        elif self.zedenv_properties["bootonzfs"] == ("no" or "0"):
            self.bootonzfs = False
        else:
            ZELogger.log({
                "level": "EXCEPTION",
                "message": (f"Property 'bootonzfs' is set to invalid value "
                            f"{self.zedenv_properties['bootonzfs']}, should be "
                            "'yes', 'no', '0', or '1'. Exiting.\n")
            }, exit_on_error=True)

        if self.bootonzfs:
            if not self.noop:
                if not os.path.isdir(self.zedenv_properties["boot"]):
                    try:
                        os.makedirs(self.zedenv_properties["boot"])
                    except PermissionError as e:
                        ZELogger.log({
                            "level": "EXCEPTION",
                            "message": ("Require Privileges to write to "
                                        f"{self.zedenv_properties['boot']}\n{e}")
                        }, exit_on_error=True)
                    except OSError as os_err:
                        ZELogger.log({"level": "EXCEPTION", "message": os_err},
                                     exit_on_error=True)
                    ZELogger.verbose_log({
                        "level": "INFO",
                        "message": ("Created mount directory "
                                    f"{self.zedenv_properties['boot']}\n")
                    }, self.verbose)

                zfs_env_dir_path = os.path.join(
                    self.zedenv_properties["boot"], self.zfs_env_dir)
                if not os.path.isdir(zfs_env_dir_path):
                    try:
                        os.makedirs(zfs_env_dir_path)
                    except PermissionError as e:
                        ZELogger.log({
                            "level": "EXCEPTION",
                            "message": (f"Require Privileges to write to "
                                        f"{zfs_env_dir_path}\n{e}")
                        }, exit_on_error=True)
                    except OSError as os_err:
                        ZELogger.log({"level": "EXCEPTION", "message": os_err},
                                     exit_on_error=True)
        else:
            if not os.path.isdir(self.zedenv_properties["boot"]):
                self.plugin_property_error("boot")

        self.grub_boot_dir = os.path.join(
            self.boot_mountpoint, self.zedenv_properties["grubsubdir"])

        if not os.path.isdir(self.grub_boot_dir):
            ZELogger.log({"level": "EXCEPTION",
                          "message": (f"Directory {self.grub_boot_dir} does not exist. "
                                      "Check 'grubsubdir' property is set correctly")
                          }, exit_on_error=True)

        self.grub_cfg = "grub.cfg"

        self.grub_cfg_path = os.path.join(self.grub_boot_dir, self.grub_cfg)

    def grub_mkconfig(self, location: str):
        env = dict(os.environ, ZPOOL_VDEV_NAME_PATH='1')
        ZELogger.verbose_log({
            "level": "INFO",
            "message": (f"Generating "
                        "the GRUB configuration.\n")
        }, self.verbose)

        grub_call = ["grub-mkconfig", "-o", location]

        try:
            grub_output = subprocess.check_call(grub_call, env=env,
                                                universal_newlines=True, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to generate GRUB config.\n{e}\n.")

        return grub_output

    def modify_bootloader(self, temp_boot: str):

        real_kernel_dir = os.path.join(self.zedenv_properties["boot"], "env")
        temp_kernel_dir = os.path.join(temp_boot, "env")

        real_old_dataset_kernel = os.path.join(real_kernel_dir, self.old_entry)
        temp_new_dataset_kernel = os.path.join(temp_kernel_dir, self.new_entry)

        if not os.path.isdir(real_old_dataset_kernel):
            ZELogger.log({
                "level": "INFO",
                "message": (f"No directory for Boot environments kernels found at "
                            f"'{real_old_dataset_kernel}', creating empty directory."
                            f"Don't forget to add your kernel to "
                            f"{real_kernel_dir}/zedenv-{self.boot_environment}.")
            })
            if not self.noop:
                try:
                    os.makedirs(temp_new_dataset_kernel)
                except PermissionError as e:
                    ZELogger.log({
                        "level": "EXCEPTION",
                        "message": f"Require Privileges to write to {temp_new_dataset_kernel}\n{e}"
                    }, exit_on_error=True)
                except OSError as os_err:
                    ZELogger.log({
                        "level": "EXCEPTION",
                        "message": os_err
                    }, exit_on_error=True)
        else:
            if not self.noop:
                try:
                    shutil.copytree(real_old_dataset_kernel, temp_new_dataset_kernel)
                except PermissionError as e:
                    ZELogger.log({
                        "level": "EXCEPTION",
                        "message": f"Require Privileges to write to {temp_new_dataset_kernel}\n{e}"
                    }, exit_on_error=True)
                except IOError as e:
                    ZELogger.log({
                        "level": "EXCEPTION",
                        "message": f"IOError writing to {temp_new_dataset_kernel}\n{e}"
                    }, exit_on_error=True)

    def setup_boot_env_tree(self):
        mount_root = os.path.join(self.zedenv_properties["boot"], self.zfs_env_dir)

        if not os.path.exists(mount_root):
            os.mkdir(mount_root)

        be_list = None
        be_list = zedenv.lib.be.list_boot_environments(self.be_root, ['name'])
        ZELogger.verbose_log(
            {"level": "INFO", "message": f"Going over list {be_list}.\n"}, self.verbose)

        for b in be_list:
            if not pyzfscmds.utility.is_snapshot(b['name']):
                be_name = pyzfscmds.utility.dataset_child_name(b['name'], False)
                
                if not zedenv.lib.be.extra_bpool():
                    # Check if 'b' is current dataset
                    if pyzfscmds.system.agnostic.dataset_mountpoint(b['name']) == "/":
                        ZELogger.verbose_log({
                            "level": "INFO",
                            "message": f"Dataset {b['name']} is root, skipping.\n"
                        }, self.verbose)
                    else:
                        be_boot_mount = os.path.join(mount_root, f"zedenv-{be_name}")
                        ZELogger.verbose_log(
                            {"level": "INFO", "message": f"Setting up {b['name']}.\n"}, self.verbose)

                        if not os.path.exists(be_boot_mount):
                            os.mkdir(be_boot_mount)

                        if not os.listdir(be_boot_mount):
                            zedenv.cli.mount.zedenv_mount(be_name,
                                                        be_boot_mount,
                                                        self.verbose, self.be_root)
                        else:
                            ZELogger.verbose_log({
                                "level": "WARNING",
                                "message": f"Mount directory {be_boot_mount} wasn't empty, skipping.\n"
                            }, self.verbose)
                else:
                    # Mount all boot datasets
                    self.be_boot = zedenv.lib.be.root("/boot")

                    be_boot_mount = os.path.join(mount_root, f"zedenv-{be_name}")
                    ZELogger.verbose_log(
                            {"level": "INFO", "message": f"Setting up {b['name']}.\n"}, self.verbose)

                    if not os.path.exists(be_boot_mount):
                            os.mkdir(be_boot_mount)

                    if not os.listdir(be_boot_mount):
                        zedenv.cli.mount.zedenv_mount("zedenv-" + be_name,
                                                    be_boot_mount,
                                                    self.verbose, self.be_boot, check_bpool=False)
                    else:
                        ZELogger.verbose_log({
                            "level": "WARNING",
                            "message": f"Mount directory {be_boot_mount} wasn't empty, skipping.\n"
                        }, self.verbose)


    def teardown_boot_env_tree(self):
        def ismount(path, boot):
            if not os.path.ismount(path):
                # This is required because `os.path.ismount()` returns False if a ZFS dataset is beeing mounted
                # again to a subfolder of itself. E.g. bpool/boot/env/zedenv-default is mounted to
                #  - `/boot` and
                #  - `/boot/zfsenv/zedenv-default`
                s1 = os.lstat(path)
                s2 = os.lstat(boot)
                return (s1.st_ino == s2.st_ino)
            else:
                return True

        mount_root = os.path.join(self.zedenv_properties["boot"], self.zfs_env_dir)
        cleanup = True

        if not os.path.exists(mount_root):
            ZELogger.verbose_log({
                "level": "INFO",
                "message": f"Mount root: '{mount_root}' doesnt exist.\n"
            }, self.verbose)
        else:
            for m in os.listdir(mount_root):
                mount_path = os.path.join(mount_root, m)
                ZELogger.verbose_log({
                    "level": "INFO",
                    "message": f"Unmounting {m}\n"
                }, self.verbose)
                if ismount(mount_path, self.boot_mountpoint):
                    try:
                        zedenv.lib.system.umount(mount_path)
                    except RuntimeError as e:
                        ZELogger.log({
                            "level": "WARNING",
                            "message": f"Failed Un-mountingdataset from '{m}'.\n{e}"
                        }, exit_on_error=True)
                        cleanup = False
                    else:
                        ZELogger.verbose_log({
                            "level": "INFO",
                            "message": f"Unmounted {m} from {mount_path}.\n"
                        }, self.verbose)
                        try:
                            os.rmdir(mount_path)
                        except OSError as ex:
                            ZELogger.verbose_log({
                                "level": "WARNING",
                                "message": f"Couldn't remove directory {mount_path}.\n{ex}\n"
                            }, self.verbose)
                            cleanup = False
                        else:
                            ZELogger.verbose_log({
                                "level": "INFO",
                                "message": f"Removed directory {mount_path}.\n"
                            }, self.verbose)

        if cleanup and os.path.exists(mount_root):
            try:
                os.rmdir(mount_root)
            except OSError as ex:
                ZELogger.verbose_log({
                    "level": "WARNING",
                    "message": f"Couldn't remove directory {mount_root}.\n{ex}\n"
                }, self.verbose)

    def post_activate(self):
        ZELogger.verbose_log({
            "level": "INFO",
            "message": (f"Creating Temporary working directory. "
                        "No changes will be made until the end of "
                        "the GRUB configuration.\n")
        }, self.verbose)

        if not self.bootonzfs:
            with tempfile.TemporaryDirectory(prefix="zedenv", suffix=self.bootloader) as t_grub:
                ZELogger.verbose_log({
                    "level": "INFO",
                    "message": f"Created {t_grub}.\n"
                }, self.verbose)

                self.modify_bootloader(t_grub)
                self.recurse_move(t_grub, self.zedenv_properties["boot"], overwrite=False)

        if self.bootonzfs:
            self.setup_boot_env_tree()

        if not self.skip_update_grub:
            try:
                self.grub_mkconfig(self.grub_cfg_path)
            except RuntimeError as e:
                ZELogger.verbose_log({
                    "level": "INFO",
                    "message": f"During 'post activate', 'grub-mkconfig' failed with:\n{e}.\n"
                }, self.verbose)
            else:
                ZELogger.verbose_log({
                    "level": "INFO",
                    "message": f"Generated GRUB menu successfully at {self.grub_cfg_path}.\n"
                }, self.verbose)

        if self.bootonzfs and not self.skip_cleanup:
            self.teardown_boot_env_tree()

    def pre_activate(self):
        pass

    def mid_activate(self, be_mountpoint: str):
        ZELogger.verbose_log({
            "level": "INFO",
            "message": f"Running {self.bootloader} mid activate.\n"
        }, self.verbose)

        replace_pattern = r'(^{real_boot}/{env}/?)(.*)(\s.*{boot}\s.*$)'.format(
            real_boot=self.zedenv_properties["boot"], env=self.env_dir, boot=self.boot_mountpoint)

        if not self.bootonzfs:
            self.modify_fstab(be_mountpoint, replace_pattern, self.new_entry)

    def post_destroy(self, target):
        self.post_activate()

    def post_create(self):
        self.post_activate()

    def post_rename(self):
        self.post_activate()
