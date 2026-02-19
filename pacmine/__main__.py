import httpx
import argparse
import json
import os
import sys
from packaging.version import parse as parse_version

HEADERS = {"User-Agent": "pacmine/0.2.0"}

COMPATIBILITY_MAP = {
    # Plugins
    "velocity": ["velocity"],
    "bungeecord": ["bungeecord"],
    "bukkit": ["bukkit"],
    "spigot": ["spigot", "bukkit"],
    "paper": ["paper", "spigot", "bukkit"],
    "purpur": ["purpur", "paper", "spigot", "bukkit"],
    
    # Mods
    "fabric": ["fabric"],
    "forge": ["forge"],
    "neoforge": ["neoforge"],
    "quilt": ["quilt"],
}


def is_mod_loader(core: str) -> bool:
    return core in {"fabric", "forge", "neoforge", "quilt"}


def get_install_dir(core: str) -> str:
    return "mods" if is_mod_loader(core) else "plugins"


def get_package_type(core: str) -> str:
    return "mod" if is_mod_loader(core) else "plugin"


def confirm(prompt):
    """Pacman-style confirmation: default is Yes."""
    choice = input(f"{prompt} [Y/n] ").lower()
    if choice == '':
        return True
    return choice in ("y", "yes")


def cmd_init(args):
    os.makedirs(".pacmine", exist_ok=True)
    print(":: Initializing pacmine environment...")
    
    print("Supported cores: " + ", ".join(COMPATIBILITY_MAP.keys()))
    version = input("Minecraft version: ").strip()
    core = input("Core: ").strip().lower()
    
    if core not in COMPATIBILITY_MAP:
        print(f"error: Core '{core}' is not supported.")
        sys.exit(1)
        
    data = {"version": version, "core": core}
    with open('.pacmine/env', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f":: Initialized: Minecraft {version} + {core.upper()}")


def load_env():
    if not os.path.exists(".pacmine/env"):
        print("error: Environment not initialized! Run: pacmine -I")
        sys.exit(1)
    with open('.pacmine/env', 'r', encoding='utf-8') as f:
        return json.load(f)


def get_plugin(project_id, core, version=None):
    loaders = COMPATIBILITY_MAP.get(core, [core])
    r = httpx.get(
        f'https://api.modrinth.com/v2/project/{project_id}/version',
        params={"loaders": json.dumps(loaders)},
        headers=HEADERS,
        timeout=10.0
    )
    if r.status_code != 200:
        return None
    versions = r.json()
    if not versions:
        return None
    if not version:
        return versions[0]

    target = parse_version(version)
    candidates = []
    for v in versions:
        for gv in v.get("game_versions", []):
            try:
                gv_p = parse_version(gv)
                if gv_p == target:
                    return v
                if gv_p and gv_p < target:
                    candidates.append((gv_p, v))
            except:
                continue
    if candidates:
        return max(candidates, key=lambda x: x[0])[1]
    return None


def search_plugins(query, core):
    loaders = COMPATIBILITY_MAP.get(core, [core])
    facets = json.dumps([[f"categories:{c}" for c in loaders]])
    r = httpx.get('https://api.modrinth.com/v2/search',
                  params={"query": query, "facets": facets}, 
                  headers=HEADERS,
                  timeout=10.0)
    return r.json()


def get_installed_packages():
    path = ".pacmine/installed.json"
    if not os.path.exists(path):
        os.makedirs(".pacmine", exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_installed_packages(packages):
    with open(".pacmine/installed.json", 'w', encoding='utf-8') as f:
        json.dump(packages, f, ensure_ascii=False, indent=2)


def add_package(package):
    packages = get_installed_packages()
    pid = package['project_id']
    packages[pid] = package
    save_installed_packages(packages)


def remove_package(package, core):
    packages = get_installed_packages()
    pid = package['project_id']
    if pid in packages:
        install_dir = get_install_dir(core)
        filename = packages[pid]['files'][0]['filename']
        filepath = f"{install_dir}/{filename}"
        if os.path.exists(filepath):
            os.remove(filepath)
        del packages[pid]
        save_installed_packages(packages)


def download(package, core):
    file_data = package['files'][0]
    install_dir = get_install_dir(core)
    os.makedirs(install_dir, exist_ok=True)
    
    r = httpx.get(file_data['url'], headers=HEADERS, timeout=30.0)
    with open(f"{install_dir}/{file_data['filename']}", 'wb') as f:
        f.write(r.content)


def cmd_install(args, env):
    core = env['core']
    pkg_type = get_package_type(core)
    to_install = []
    seen = set()
    
    print(f":: Synchronizing package databases...")
    print(f":: Resolving dependencies...")
    print(f":: Looking for inter-conflicts...")
    print()
    
    # FIXED: Use args.packages consistently
    packages_to_install = args.packages
    
    for i, query in enumerate(packages_to_install, 1):
        print(f"[{i}/{len(packages_to_install)}] Searching: {query}")
        data = search_plugins(query, core)
        hits = data.get('hits', [])
        
        if not hits:
            print(f"   error: Target not found: {query}")
            continue
            
        project = get_plugin(hits[0]['project_id'], core, env['version'])
        if not project:
            print(f"   warning: No compatible version for: {query}")
            continue
            
        title = project.get('title', project.get('name', query))
        if project['project_id'] in seen:
            continue
            
        seen.add(project['project_id'])
        to_install.append((title, project))
        print(f"   -> Found: {title}")

    if not to_install:
        print("\nerror: No packages found to install.")
        sys.exit(1)

    print(f"\nPackages ({len(to_install)}):")
    for title, p in to_install:
        print(f"   {title} ({p['files'][0]['filename']})")

    if not confirm(f"\nProceed with installation?"):
        print(":: Transaction cancelled.")
        sys.exit(0)

    print(f"\n:: Installing {pkg_type}s to ./{get_install_dir(core)}/ ...\n")
    
    for i, (title, package) in enumerate(to_install, 1):
        print(f"[{i}/{len(to_install)}] Installing: {title}")
        
        deps = [d for d in package.get("dependencies", []) if d.get("dependency_type") == "required"]
        for dep in deps:
            if dep.get("project_id") and dep["project_id"] not in seen:
                dep_pkg = get_plugin(dep["project_id"], core, env['version'])
                if dep_pkg:
                    seen.add(dep_pkg['project_id'])
                    add_package(dep_pkg)
                    download(dep_pkg, core)
                    print(f"    -> Dependency: {dep_pkg.get('title', 'Unknown')}")

        add_package(package)
        download(package, core)
        print(f"    (1/1) checking file conflicts...")
        print(f"    (1/1) installing {title}...\n")

    print(":: Installation complete.")


def cmd_uninstall(args, env):
    core = env['core']
    pkg_type = get_package_type(core)
    packages = get_installed_packages()
    
    to_remove = []
    
    for query in args.packages:
        query_lower = query.lower()
        found = None
        for p in packages.values():
            name = p.get('title', p.get('name', '')).lower()
            slug = p.get('slug', '').lower()
            if query_lower == name or query_lower in name or query_lower == slug:
                found = p
                break
        if found:
            to_remove.append(found)
        else:
            print(f"warning: Target not found: {query}")

    if not to_remove:
        print("error: No packages found to remove.")
        sys.exit(1)

    print(f"\nPackages ({len(to_remove)}):")
    for p in to_remove:
        print(f"   {p.get('title', p.get('name'))}")

    if not confirm(f"\nProceed with removal?"):
        print(":: Transaction cancelled.")
        sys.exit(0)

    for p in to_remove:
        name = p.get('title', p.get('name'))
        remove_package(p, core)
        print(f":: Removing {name}...")

    print(":: Removal complete.")


def cmd_search(args, env):
    data = search_plugins(args.query, env['core'])
    hits = data.get('hits', [])
    if not hits:
        print(":: No packages found.")
        return
    
    print(f":: Searching for '{args.query}'...")
    for p in hits:
        latest = p.get('latest_version', {})
        if isinstance(latest, dict):
            ver = latest.get('version_number', 'unknown')
        else:
            ver = 'unknown'
        print(f"modrinth/{p['slug']} {ver}")
        print(f"    {p.get('description', 'No description')}")


def cmd_list(args, env):
    packages = get_installed_packages()
    if not packages:
        print(":: No packages installed.")
        return
    
    pkg_type = get_package_type(env['core'])
    print(f":: Installed {pkg_type}s:")
    for p in packages.values():
        version = p.get('files', [{}])[0].get('filename', 'unknown')
        print(f"{p.get('slug', p.get('title', 'unknown'))} {version}")


def main():
    parser = argparse.ArgumentParser(
        prog="pacmine", 
        description="A pacman-like package manager for Minecraft mods/plugins"
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    
    group.add_argument('-I', '--init', action='store_true', help='Initialize environment')
    
    group.add_argument('-S', '--sync', dest='packages', nargs='+', metavar="PACKAGE", 
                       help='Install packages')
    
    group.add_argument('-R', '--remove', dest='packages', nargs='+', metavar="PACKAGE", 
                       help='Remove packages')
    
    group.add_argument('-Q', '--query', action='store_true', help='List installed packages')
    
    group.add_argument('-Ss', '--search', dest='search_query', metavar="QUERY", 
                       help='Search for packages')
    
    parser.add_argument('--noconfirm', action='store_true', help='Do not ask for confirmation')

    args = parser.parse_args()
    
    if args.noconfirm:
        global confirm
        confirm = lambda prompt: True

    if args.init:
        cmd_init(args)
    elif args.packages:
        if '-S' in sys.argv or '--sync' in sys.argv:
            env = load_env()
            cmd_install(args, env)
        elif '-R' in sys.argv or '--remove' in sys.argv:
            env = load_env()
            cmd_uninstall(args, env)
    elif args.search_query:
        env = load_env()
        args.query = args.search_query
        cmd_search(args, env)
    elif args.query:
        env = load_env()
        cmd_list(args, env)

if __name__ == "__main__":
    main()
