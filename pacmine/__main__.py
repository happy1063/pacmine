import httpx
import argparse
import json
import os
import sys
from packaging import version as pkg_version
from packaging.version import parse as parse_version
import re

HEADERS = {"User-Agent": "pacmine/0.0.1"}

COMPATIBILITY_MAP = {
    "velocity": ["velocity"],
    "bungeecord": ["bungeecord"],
    "bukkit": ["bukkit", "spigot", "paper", "purpur"],
    "spigot": ["spigot", "paper", "purpur"],
    "paper": ["paper", "purpur"],
    "purpur": ["purpur"]
}


def confirm(prompt, yes):
    if yes:
        return True
    return input(f"{prompt} [y/N]: ").lower() == "y"


def normalize_version(v):
    try:
        return pkg_version.parse(v)
    except:
        return None


def init(args, env=None):
    os.makedirs(".pacmine", exist_ok=True)
    version = input("Version: ")
    core = input("Core: ")
    if core not in COMPATIBILITY_MAP:
        print("Not supported")
        sys.exit(1)
    data = {"version": version, "core": core}
    with open('.pacmine/env', 'w', encoding='utf-8') as f:
        json.dump(data, f)


def load_env():
    if not os.path.exists(".pacmine/env"):
        print("Environment not initialized! Run: pacmine init")
        sys.exit(1)
    with open('.pacmine/env', 'r', encoding='utf-8') as f:
        return json.load(f)


def get_plugin(project_id, core, version=None):
    r = httpx.get(
        f'https://api.modrinth.com/v2/project/{project_id}/version', headers=HEADERS)
    all_versions = r.json()

    if not version:
        return all_versions[0]

    target_version = parse_version(version)
    compatible_versions = []

    for v in all_versions:
        for gv in v["game_versions"]:
            gv_parsed = parse_version(gv)
            if gv_parsed is not None:
                if gv_parsed <= target_version:
                    compatible_versions.append((gv_parsed, v))
                break

    if compatible_versions:
        closest = max(compatible_versions, key=lambda x: x[0])[1]
        print(f"Exact version not found, using closest compatible: {
              closest['game_versions'][-1]}")
        return closest

    return None


def search_plugins(query, core):
    params = {
        "query": query,
        "facets": json.dumps([[f"categories:{c}" for c in COMPATIBILITY_MAP.get(core, [core])]])
    }
    r = httpx.get('https://api.modrinth.com/v2/search',
                  params=params, headers=HEADERS)
    return r.json()

    def get_plugin(project_id, core, version=None):
        params = {"loaders": json.dumps(COMPATIBILITY_MAP.get(core))}
        r = httpx.get(
            f'https://api.modrinth.com/v2/project/{project_id}/version', headers=HEADERS)
        all_versions = r.json()

        if not version:
            return all_versions[0]

        target_version = parse_version(version)
        compatible_versions = []

        for v in all_versions:
            for gv in v["game_versions"]:
                gv_parsed = parse_version(gv)
                if gv_parsed is not None:
                    diff = abs(target_version - gv_parsed)
                    compatible_versions.append((diff, v))
                    break

        if compatible_versions:
            closest = min(compatible_versions, key=lambda x: x[0])[1]
            print(f"Exact version not found, using closest compatible: {
                  closest['game_versions'][-1]}")
            return closest

        return None


def search(args, env):
    data = search_plugins(args.query, env['core'])
    hits = data.get('hits', [])
    if not hits:
        print("No plugins found.")
        return
    print(f"Found {len(hits)} plugins:")
    for plugin in hits:
        print(f" - {plugin['title']}")


def get_installed_plugins():
    os.makedirs(".pacmine", exist_ok=True)
    path = ".pacmine/plugins.json"
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def add_plugin(plugin):
    plugins = get_installed_plugins()
    pid = plugin['project_id']
    if pid not in plugins or plugins[pid]['files'][0]['id'] != plugin['files'][0]['id']:
        plugins[pid] = plugin
    with open(".pacmine/plugins.json", 'w', encoding='utf-8') as f:
        json.dump(plugins, f)


def remove_plugin(plugin):
    plugins = get_installed_plugins()
    pid = plugin['project_id']
    if pid in plugins:
        os.remove(f"plugins/{plugins[pid]['files'][0]['filename']}")
        del plugins[pid]
    with open(".pacmine/plugins.json", 'w', encoding='utf-8') as f:
        json.dump(plugins, f)


def uninstall(args, env):
    plugins = get_installed_plugins()
    found = None
    for p in plugins.values():
        if args.query.lower() == p['name'].lower() or args.query.lower() in p['name'].lower():
            found = p
            break
    if not found:
        print("Plugin not found")
        sys.exit(1)
    if confirm("Uninstall?", args.yes):
        remove_plugin(found)
        print(f"Uninstalled: {found['name']}")


def download(plugin):
    file_data = plugin['files'][0]
    url = file_data['url']
    os.makedirs("plugins", exist_ok=True)
    r = httpx.get(url, headers=HEADERS)
    with open(f"plugins/{file_data['filename']}", 'wb') as f:
        f.write(r.content)


def install(args, env):
    data = search_plugins(args.query, env['core'])
    hits = data.get('hits', [])
    if not hits:
        print("Plugin not found.")
        sys.exit(1)

    plugin = get_plugin(hits[0]['project_id'], env['core'], env['version'])
    if not plugin:
        print("No compatible version found.")
        sys.exit(1)

    deps = [d for d in plugin.get(
        "dependencies", []) if d["dependency_type"] == "required"]

    if not confirm("Install?", args.yes):
        sys.exit(0)

    add_plugin(plugin)
    for dep in deps:
        dep_plugin = get_plugin(dep["project_id"], env['core'], env['version'])
        add_plugin(dep_plugin)
        download(dep_plugin)
        print(f"Installed dependency: {dep_plugin['name']}")

    download(plugin)
    print(f"Installed: {plugin['name']}")


def list_plugins(args, env):
    plugins = get_installed_plugins()
    if not plugins:
        print("No plugins installed.")
        return
    print("Installed plugins:")
    for p in plugins.values():
        print(f" - {p['name']} ({p['files'][0]['filename']})")


commands = {
    "init": init,
    "search": search,
    "install": install,
    "list": list_plugins,
    "uninstall": uninstall
}


def main():
    parser = argparse.ArgumentParser(
        prog="pacmine", description="Simple plugin manager for Minecraft servers")
    sp = parser.add_subparsers(dest="command", required=True)

    sp.add_parser("init", help="Initialize server")

    search_parser = sp.add_parser("search", help="Search plugins")
    search_parser.add_argument("query")

    install_parser = sp.add_parser("install", help="Install plugin")
    install_parser.add_argument("query")
    install_parser.add_argument("-y", "--yes", action="store_true")

    sp.add_parser("list", help="List installed plugins")

    uninstall_parser = sp.add_parser("uninstall", help="Uninstall plugin")
    uninstall_parser.add_argument("query")
    uninstall_parser.add_argument("-y", "--yes", action="store_true")

    args = parser.parse_args()
    env = None
    if args.command != "init":
        env = load_env()

    func = commands.get(args.command)
    if callable(func):
        func(args, env)


if __name__ == "__main__":
    main()
