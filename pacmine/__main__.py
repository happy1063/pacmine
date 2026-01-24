import httpx
import argparse
import json
import os
import sys

COMPATIBILITY_MAP = {
    "bukkit": ["bukkit"],
    "spigot": ["spigot", "bukkit"],
    "paper": ["paper", "spigot", "bukkit"],
    "purpur": ["purpur", "paper", "spigot", "bukkit"]
}
HEADERS = {"User-Agent": "pacmine/0.1.0"}

def confirm(prompt, yes):
    if yes:
        return True
    return input(f"{prompt} [y/N]: ").lower() == "y"

def init(args):
    dir_exists = os.path.exists(".pacmine/")
    if not dir_exists:
        os.mkdir(".pacmine/")
    version = input("Version: ")
    core = input("Core: ")
    if not core in COMPATIBILITY_MAP:
        print("Not supported")
        sys.exit(1)
    data = {
        'version': version,
        'core': core
    }
    
    with open('.pacmine/env', 'w', encoding='utf-8') as f:
        f.write(json.dumps(data))
    
def load_env():
    env_exists = os.path.exists(".pacmine/env")  
    if not env_exists:
        print("Environment not initialized!")
        print("Exec: pacmine init")
        sys.exit(1)

    f = open('.pacmine/env', 'r', encoding='utf-8')
    env = json.loads(f.read())
    
    return env

def search_plugins(query, core, version):
    params = {}
    params["query"] = query
    params["facets"] = json.dumps([[f"categories:{c}" for c in COMPATIBILITY_MAP.get(core, [core])],[f"versions:{version}"]])

    r = httpx.get('https://api.modrinth.com/v2/search', params=params, headers=HEADERS)
    data = json.loads(r.text)
    return data   

def get_plugin(project_id, core, version):
    params = {}
    params["loaders"] = json.dumps(COMPATIBILITY_MAP.get(core))
    params["game_versions"] = version

    r = httpx.get(f'https://api.modrinth.com/v2/project/{project_id}/version', params=params, headers=HEADERS)
    data = json.loads(r.text)
    return data[0]      

def search(args,env):
    core = env['core']
    version = env['version']
    query = args.query

    print(f"Searching plugins... {version} {core}")
    data = search_plugins(query, core, version)
    hits = data.get('hits')
    if not hits or len(hits) < 1:
        print(f"Error: {data}")
        return

    print(f"Founded plugins({len(hits)}): ")
    for plugin in data.get('hits'):
        print(f"'{plugin['title']}'")

def get_installed_plugins():
    env_exists = os.path.exists(".pacmine/env")  
    if not env_exists:
        print("Environment not initialized!")
        print("Exec: pacmine init")
        sys.exit(1) 

    plugins_exists = os.path.exists(".pacmine/plugins.json")
    if not plugins_exists:
        with open('.pacmine/plugins.json', 'w', encoding='utf-8') as f:
            f.write("{}")
        return {}

    f = open('.pacmine/plugins.json','r',encoding='utf-8')
    data = json.loads(f.read())
    return data

def add_plugin(plugin):
    env_exists = os.path.exists(".pacmine/env")  
    if not env_exists:
        print("Environment not initialized!")
        print("Exec: pacmine init")
        sys.exit(1) 

    plugins_exists = os.path.exists(".pacmine/plugins.json")
    if not plugins_exists:
        with open('.pacmine/plugins.json', 'w', encoding='utf-8') as f:
            f.write("{}")

    plugins = get_installed_plugins()
    if plugin['project_id'] in plugins and plugin['files'][0]['id'] == plugins[plugin['project_id']]['files'][0]['id']:
        sys.exit(0)
    else:    
        plugins[plugin['project_id']]=plugin   
    f = open('.pacmine/plugins.json','w',encoding="utf-8")    
    f.write(json.dumps(plugins))
    f.close()

def remove_plugin(plugin):
    env_exists = os.path.exists(".pacmine/env")  
    if not env_exists:
        print("Environment not initialized!")
        print("Exec: pacmine init")
        sys.exit(1)   

    plugins_exists = os.path.exists(".pacmine/plugins.json")
    if not plugins_exists:
        with open('.pacmine/plugins.json', 'w', encoding='utf-8') as f:
            f.write("{}")
            print("Plugin not installed")
            sys.exit(1)

    plugins = get_installed_plugins()

    if plugin['project_id'] in plugins:
        file_data = plugin['files'][0]
        file_name = file_data['filename']
        os.remove(f"plugins/{file_name}")
        del plugins[plugin['project_id']]
    else:
        print("Plugin not installed")
        
    f = open('.pacmine/plugins.json','w',encoding='utf-8')    
    f.write(json.dumps(plugins))
    f.close()
    return     

def uninstall(args,env):
    core = env['core']
    version = env['version']
    query = args.query

    plugins = get_installed_plugins()

    found_plugin = None

    for _,data in plugins.items():
        if query.lower() == data['name'].lower():
            found_plugin = data
            break
            
    if not found_plugin:
        for _,data in plugins.items():
            if query.lower() in data['name'].lower():
                found_plugin = data
                break

    if not found_plugin:
        print("Plugin not found")
        sys.exit(1)

    if not confirm("Uninstall?", args.yes):
        sys.exit(0)

    remove_plugin(found_plugin)

def download(plugin):
    file_data = plugin['files'][0]
    file_name = file_data['filename']
    file_url = file_data['url']
    r = httpx.get(file_url, headers=HEADERS)
    with open(f'plugins/{file_name}','wb') as f:
        f.write(r.content)
    
def install(args,env):
    core = env['core']
    version = env['version']
    query = args.query

    print(f"Searching plugins... {version} {core}")
    data = search_plugins(query, core, version)
    hits = data.get('hits')
    if not hits or len(hits) < 1:
        print(f"Error: {data}")
        sys.exit(1)

    plugin = get_plugin(hits[0]['project_id'],core,version)
    deps = plugin.get("dependencies", [])
    required = [d for d in deps if d["dependency_type"] == "required"]
    file_data = plugin['files'][0]
    file_name = file_data['filename']

    print(f"Founded: '{plugin['name']}' {file_name}")
    if len(required) > 0:
        print("Dependencies: ")
        for dep in required:
            print(f" {dep['project_id']['name']}")

    if not confirm("Install?", args.yes):
        sys.exit(0)

    os.makedirs("plugins", exist_ok=True)

    add_plugin(plugin)

    for dep in required:
        dep_plugin = get_plugin(dep["project_id"], core, version)
        add_plugin(dep_plugin)
        download(dep_plugin)
        print(f"Installed dependency: {dep_plugin['name']}")

    download(plugin)
    
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
        prog="pacmine",
        description="Simple plugin manager for minecraft servers."
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize server")

    search = subparsers.add_parser("search", help="Search plugins")
    search.add_argument("query")

    install = subparsers.add_parser("install", help="Install plugin")
    install.add_argument("query")
    install.add_argument("-y", "--yes", action="store_true")
    
    list = subparsers.add_parser("list", help="Show list of installed plugins")   

    uninstall = subparsers.add_parser("uninstall", help="Uninstall plugin")
    uninstall.add_argument("query")
    uninstall.add_argument("-y", "--yes", action="store_true")
    
    args = parser.parse_args()
    command = args.command

    if command == "init":
        commands.get(command)(args)
        return
        
    env = load_env()
    
    func = commands.get(command)
    if callable(func):
        func(args, env)
    
    
if __name__ == "__main__":
    main()
