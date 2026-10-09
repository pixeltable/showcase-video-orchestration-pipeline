#!/usr/bin/env python3
"""Apply the Pursuit and Video-MME catalogs for every path set in an isolated home.

No rows are inserted, so no model is called. Each set is applied twice: the second apply
must be a no-op.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

PURSUIT_PATH_SETS = ({'1'}, {'1', '2'}, {'1', '1L', '2', '3', '4', '5'}, {'3'})
VIDEOMME_PATH_SETS = ({'1', '2'}, {'1', '1L', '2', '3', '5'})


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix='pxt-apply-'))
    os.environ['PIXELTABLE_HOME'] = str(home)
    os.environ['ENABLE_FAL'] = os.environ['ENABLE_NOVA'] = '1'
    print(f'PIXELTABLE_HOME={home}')

    from video_benchmark import schema
    from video_benchmark.config import load_config
    from video_benchmark.videomme import schema as vm_schema
    from video_benchmark.videomme.runner import videomme_config

    config = load_config()
    for paths in PURSUIT_PATH_SETS:
        for oss_asr in ('whisper', 'whisperx', 'gemini') if '3' in paths else (config.oss_asr,):
            schema.reset_catalog()
            for _ in range(2):
                schema.apply_schema(replace(config, oss_asr=oss_asr), paths)
            print(f'Pursuit paths {sorted(paths)} (ASR {oss_asr}): ok')
    vm_config = videomme_config(config)
    for paths in VIDEOMME_PATH_SETS:
        vm_schema.reset_catalog()
        for _ in range(2):
            vm_schema.apply_schema(vm_config, schema.plan_paths(vm_config, paths))
        print(f'Video-MME paths {sorted(paths)}: ok')
    print('Schema apply smoke passed')
    # Pixeltable leaves its Postgres running after exit; stop it and delete the throwaway home.
    from pixeltable_pgserver import pg_ctl

    pg_ctl(['-m', 'fast', '-w', 'stop'], pgdata=home / 'pgdata')
    shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
