#  Drakkar-Software OctoBot-Tentacles-Manager
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library.
import aiofiles
from os import path, listdir
from shutil import copyfile, copytree, rmtree
from asyncio import gather

from octobot_tentacles_manager.base_worker.tentacle_worker import TentacleWorker
from octobot_tentacles_manager.constants import PYTHON_INIT_FILE, TENTACLE_MODULE_FOLDERS
from octobot_tentacles_manager.tentacle_data.tentacle_data import TentacleData
from octobot_tentacles_manager.util.tentacle_explorer import load_tentacle_with_metadata


class InstallWorker(TentacleWorker):

    async def install_tentacles(self, name_filter=None) -> int:
        await self.create_missing_tentacles_arch()
        self.reset_worker()
        self.progress = 1
        all_tentacle_data = await load_tentacle_with_metadata(self.reference_tentacles_root)
        to_install_tentacles = [tentacle_data
                                for tentacle_data in all_tentacle_data
                                if self._should_tentacle_data_be_processed(tentacle_data, name_filter)]
        self.total_steps = len(to_install_tentacles)
        self.register_to_process_tentacles_modules(to_install_tentacles)
        await gather(*[self._install_tentacle(tentacle_data) for tentacle_data in to_install_tentacles])
        await self.refresh_tentacle_config_file()
        self.log_summary()
        return len(self.errors)

    def _should_tentacle_data_be_processed(self, tentacle_data, name_filter):
        return name_filter is None or tentacle_data.name in name_filter

    async def _install_tentacle(self, tentacle_data):
        try:
            if tentacle_data.name not in self.processed_tentacles_modules:
                self.processed_tentacles_modules.append(tentacle_data.name)
                await self.handle_requirements(tentacle_data, self._try_install_from_requirements)
                target_tentacle_path = path.join(self.tentacle_path, tentacle_data.tentacle_type)
                tentacle_module_path = path.join(target_tentacle_path, tentacle_data.name)
                self._update_tentacle_folder(tentacle_data)
                await self._update_tentacle_type_init_file(tentacle_data, target_tentacle_path)
                await self._create_tentacle_type_init_file(tentacle_data, tentacle_module_path)
                self.import_tentacle_config_if_any(tentacle_module_path)
                self.logger.info(f"[{self.progress}/{self.total_steps}] installed {tentacle_data}")
        except Exception as e:
            message = f"Error when installing {tentacle_data.name}: {e}"
            self.errors.append(message)
            self.logger.exception(e, True, message)
        finally:
            self.progress += 1

    async def _try_install_from_requirements(self, tentacle_data, missing_requirements):
        for requirement, version in missing_requirements.items():
            if self._is_requirement_satisfied(requirement, version, tentacle_data,
                                              self.fetched_for_requirements_tentacles_versions):
                to_install_tentacle = TentacleData.find(self.fetched_for_requirements_tentacles, requirement)
                if to_install_tentacle is not None:
                    await self._install_tentacle(to_install_tentacle)
                else:
                    raise RuntimeError(f"Can't find {requirement} tentacle required for {tentacle_data.name}")

    def _update_tentacle_folder(self, tentacle_data):
        reference_tentacle_path = path.join(tentacle_data.tentacle_path, tentacle_data.name)
        target_tentacle_path = path.join(self.tentacle_path, tentacle_data.tentacle_type, tentacle_data.name)
        for tentacle_file in listdir(reference_tentacle_path):
            file_or_dir = path.join(reference_tentacle_path, tentacle_file)
            target_file_or_dir = path.join(target_tentacle_path, tentacle_file)
            if path.isfile(file_or_dir):
                copyfile(file_or_dir, target_file_or_dir)
            else:
                if tentacle_file in TENTACLE_MODULE_FOLDERS:
                    if path.exists(target_file_or_dir):
                        rmtree(target_file_or_dir)
                    copytree(file_or_dir, target_file_or_dir)

    @staticmethod
    async def _update_tentacle_type_init_file(tentacle_data, target_tentacle_path):
        init_content = ""
        init_file = path.join(target_tentacle_path, PYTHON_INIT_FILE)
        if path.isfile(init_file):
            async with aiofiles.open(init_file, "r") as init_file_r:
                init_content = await init_file_r.read()
        if tentacle_data.name not in init_content:
            init_content = f"{init_content}{TentacleWorker._get_single_module_init_line(tentacle_data)}\n"
            async with aiofiles.open(init_file, "w+") as init_file_w:
                await init_file_w.write(init_content)

    @staticmethod
    async def _create_tentacle_type_init_file(tentacle_data, tentacle_module_path):
        init_file = path.join(tentacle_module_path, PYTHON_INIT_FILE)
        init_content = InstallWorker._get_init_block(tentacle_data)
        async with aiofiles.open(init_file, "w+") as init_file_w:
            await init_file_w.write(init_content)

    @staticmethod
    def _get_init_block(tentacle_data):
        return f"""from octobot_tentacles_manager.api.inspector import check_tentacle
from octobot_commons.logging.logging_util import get_logger

if check_tentacle('{tentacle_data.version}', '{tentacle_data.name}', '{tentacle_data.origin_package}'):
    try:
        {TentacleWorker._get_single_module_init_line(tentacle_data)}
    except Exception as e:
        get_logger('TentacleLoader').exception(e, True, f'Error when loading {tentacle_data.name}: {{e}}')
"""
