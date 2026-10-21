#!/usr/bin/env python3
"""Compile and run pure protocol/planning tests; never open USB devices."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def version(path):
    return tuple(int(x) for x in path.name.split('-')[0].split('.'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dotnet', default=shutil.which('dotnet'), help='Path to a .NET 8 SDK dotnet executable')
    args = parser.parse_args()
    if not args.dotnet:
        parser.error('Install the .NET 8 SDK or specify --dotnet /path/to/dotnet')
    dotnet = Path(args.dotnet).resolve()
    runtime_root = dotnet.parent
    sdk = max((p for p in (runtime_root / 'sdk').iterdir() if p.name.startswith('8.')), key=version)
    pack = max((p for p in (runtime_root / 'packs/Microsoft.NETCore.App.Ref').iterdir() if p.name.startswith('8.')), key=version)
    root = Path(__file__).resolve().parents[1]
    out = root / '.test-build'
    out.mkdir(exist_ok=True)
    csc = sdk / 'Roslyn/bincore/csc.dll'
    references = list((pack / 'ref/net8.0').glob('*.dll'))
    for name, sources in [
        ('ProtocolTests', ['src/Protocol.cs', 'tests/ProtocolTests.cs']),
        ('PlanTests', ['src/Protocol.cs', 'src/ProfileService.cs', 'src/WindowsHid.cs', 'tests/PlanTests.cs']),
    ]:
        target = out / (name + '.dll')
        command = [str(dotnet), str(csc), '/nologo', '/target:exe', '/langversion:7.3', '/nostdlib+', '/out:' + str(target)]
        command += ['/reference:' + str(p) for p in references]
        command += [str(root / p) for p in sources]
        subprocess.run(command, check=True)
        target.with_suffix('.runtimeconfig.json').write_text(json.dumps({
            'runtimeOptions': {'tfm': 'net8.0', 'framework': {'name': 'Microsoft.NETCore.App', 'version': pack.name}}
        }), encoding='utf-8')
        subprocess.run([str(dotnet), str(target)], check=True)


if __name__ == '__main__':
    main()
