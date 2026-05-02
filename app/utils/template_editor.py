import os
import shutil
import json
import re
import subprocess

from app.services.image_personalization_service import StoreImagePersonalizationService


def _escape_js(value: str) -> str:
    return value.replace('"', '\\"') if isinstance(value, str) else value


def _get_ignore_patterns():
    """Return a function to ignore certain directories when copying template."""
    def ignore_patterns(directory, files):
        # Exclude .git, node_modules, .env files, and other unnecessary dirs
        ignored = set()
        for f in files:
            if f in {'.git', 'node_modules', '.env', '.env.local', '.env.*.local'}:
                ignored.add(f)
        return ignored
    return ignore_patterns


def _init_git_repo(target_dir: str):
    """Initialize a fresh Git repository for the project."""
    try:
        subprocess.run(['git', 'init'], cwd=target_dir, check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'asea@project.local'], cwd=target_dir, check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'ASEA Project'], cwd=target_dir, check=True, capture_output=True)
        git_exclude = os.path.join(target_dir, '.git', 'info', 'exclude')
        os.makedirs(os.path.dirname(git_exclude), exist_ok=True)
        with open(git_exclude, 'a', encoding='utf-8') as f:
            f.write('\nnode_modules/\ndist/\nbuild/\n.env\n.env.*\n.vercel/\n.preview-server.json\n')
        # Initial commit
        subprocess.run(['git', 'add', '.'], cwd=target_dir, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Initial project from template'], cwd=target_dir, check=True, capture_output=True)
    except Exception as e:
        # Log but don't fail if git init fails
        print(f"Warning: Failed to initialize git repo for {target_dir}: {e}")


def create_project_from_template(base_dir: str, template_name: str, target_dir: str, config: dict):
    """
    Clones the template directory and injects the project-specific config.
    base_dir should be the root ASEA folder.
    Each project gets its own isolated Git repository.
    """
    template_path = os.path.join(base_dir, template_name)

    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)

    # Copy all files EXCEPT .git, node_modules, and .env files
    shutil.copytree(template_path, target_dir, ignore=_get_ignore_patterns())

    # Normalize config with sensible fallbacks derived from the spec
    store_name = config.get('store_name', 'ASEA Store')
    tagline = config.get('tagline', 'Powered by ASEA')
    normalized_config = {
        'store_name': store_name,
        'tagline': tagline,
        'hero_badge': config.get('hero_badge', store_name),
        'hero_title': config.get('hero_title', f"{store_name} — {tagline}"),
        'hero_subtitle': config.get('hero_subtitle', tagline),
        'hero_cta': config.get('hero_cta', 'Shop Featured'),
    }

    # Run replacements
    _update_package_json(target_dir, normalized_config)
    _update_index_html(target_dir, normalized_config)
    _update_settings_store(target_dir, normalized_config)
    _update_layout_components(target_dir, normalized_config)
    _update_homepage_content(target_dir, normalized_config)
    _personalize_homepage_images(target_dir, normalized_config)
    _update_home_splash(target_dir, normalized_config)
    _write_env_file(target_dir, normalized_config)
    # Initialize fresh Git repository for this project
    _init_git_repo(target_dir)


def _update_package_json(target_dir: str, config: dict):
    path = os.path.join(target_dir, 'package.json')
    if not os.path.exists(path): return
    
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    store_name_slug = re.sub(r'[^a-zA-Z0-9-]', '-', config.get('store_name', 'asea-store').lower())
    data['name'] = store_name_slug
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def _update_index_html(target_dir: str, config: dict):
    path = os.path.join(target_dir, 'index.html')
    if not os.path.exists(path): return
    
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    store_name = config.get('store_name', 'ASEA Store')
    content = re.sub(r'<title>.*?</title>', f'<title>{store_name}</title>', content)
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

def _update_settings_store(target_dir: str, config: dict):
    path = os.path.join(target_dir, 'src', 'store', 'useSettingsStore.js')
    if not os.path.exists(path): return
    
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    store_name = config.get('store_name', 'My Store')
    tagline = config.get('tagline', 'Created by ASEA')
    
    content = content.replace("storeName: ''", f"storeName: '{store_name}'")
    content = content.replace("storeDescription: ''", f"storeDescription: '{tagline}'")
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

def _update_layout_components(target_dir: str, config: dict):
    store_name = config.get('store_name', 'My Store')
    tagline = config.get('tagline', 'Created by ASEA')
    
    # Components to modify
    files_to_check = [
        os.path.join(target_dir, 'src', 'components', 'Header.jsx'),
        os.path.join(target_dir, 'src', 'components', 'Footer.jsx'),
        os.path.join(target_dir, 'src', 'components', 'BrandWrapper.jsx'),
        os.path.join(target_dir, 'src', 'pages', 'Login.jsx'),
        os.path.join(target_dir, 'src', 'pages', 'Signup.jsx'),
        os.path.join(target_dir, 'src', 'pages', 'admin', 'AdminLogin.jsx'),
    ]
    
    for path in files_to_check:
        if not os.path.exists(path): continue
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        content = re.sub(r'E-Commerce', store_name, content, flags=re.IGNORECASE)
        # Update specific footer tagline if matched
        content = re.sub(r'Crafting premium digital experiences.*?\.', tagline, content)
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)


def _update_homepage_content(target_dir: str, config: dict):
    """Inject hero defaults into the public home content config."""
    path = os.path.join(target_dir, 'src', 'utils', 'contentApi.js')
    if not os.path.exists(path):
        return

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    replacements = {
        r"heroBadge:\s*\".*?\"": f"heroBadge: \"{_escape_js(config.get('hero_badge', ''))}\"",
        r"heroTitle:\s*\".*?\"": f"heroTitle: \"{_escape_js(config.get('hero_title', ''))}\"",
        r"heroSubtitle:\s*\".*?\"": f"heroSubtitle: \"{_escape_js(config.get('hero_subtitle', ''))}\"",
        r"heroCtaText:\s*\".*?\"": f"heroCtaText: \"{_escape_js(config.get('hero_cta', ''))}\"",
    }

    for pattern, replacement in replacements.items():
        content = re.sub(pattern, replacement, content, count=1)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _update_home_splash(target_dir: str, config: dict):
    """Replace the hard-coded splash texts on the Home page."""
    path = os.path.join(target_dir, 'src', 'pages', 'Home.jsx')
    if not os.path.exists(path):
        return

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    store_name = config.get('store_name', 'ASEA Store')
    tagline = config.get('tagline', 'Powered by ASEA')

    # Update the splash title and tagline
    content = content.replace(
        'ASEA <span className="text-indigo-600">STORE</span>',
        f"{store_name.upper()} <span className=\"text-indigo-600\">STORE</span>",
    )
    content = content.replace(
        'Refining Experience',
        tagline,
    )

    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _write_env_file(target_dir: str, config: dict):
    """Generate .env from .env.example with VITE_APP_NAME set to the store name."""
    example_path = os.path.join(target_dir, '.env.example')
    env_path = os.path.join(target_dir, '.env')

    store_name = config.get('store_name', 'ASEA Store')

    if os.path.exists(example_path):
        with open(example_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Replace the VITE_APP_NAME value with the actual store name
        content = re.sub(
            r'VITE_APP_NAME=.*',
            f'VITE_APP_NAME={store_name}',
            content
        )

        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(content)
    else:
        # No .env.example found — write a minimal .env
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(f'VITE_APP_NAME={store_name}\n')


def _personalize_homepage_images(target_dir: str, config: dict):
    """
    Rule-based slot mapping with AI-generated search queries:
    - hero image in src/utils/contentApi.js
    - discovery grid images in src/pages/Home.jsx
    """
    store_name = config.get('store_name', 'ASEA Store')
    store_description = config.get('store_description', config.get('tagline', 'Modern ecommerce store'))

    selected = StoreImagePersonalizationService.get_store_images(
        store_name=store_name,
        store_description=store_description,
    )

    if not selected:
        return

    # 1) Replace hero image in contentApi.js
    content_api_path = os.path.join(target_dir, 'src', 'utils', 'contentApi.js')
    if os.path.exists(content_api_path):
        with open(content_api_path, 'r', encoding='utf-8') as f:
            content_api = f.read()

        content_api = re.sub(
            r'heroImage:\s*".*?"',
            f'heroImage: "{_escape_js(selected["hero"])}"',
            content_api,
            count=1,
        )

        with open(content_api_path, 'w', encoding='utf-8') as f:
            f.write(content_api)

    # 2) Replace first three discovery image URLs in Home.jsx
    home_path = os.path.join(target_dir, 'src', 'pages', 'Home.jsx')
    if os.path.exists(home_path):
        with open(home_path, 'r', encoding='utf-8') as f:
            home_content = f.read()

        discovery_match = re.search(
            r'(const\s+discoveryItems\s*=\s*\[)([\s\S]*?)(\]\s*;)',
            home_content,
        )

        if discovery_match:
            block = discovery_match.group(2)
            replacement_urls = [selected['essentials'], selected['arrivals'], selected['sale']]
            idx = 0

            def _replace_image(match):
                nonlocal idx
                if idx >= len(replacement_urls):
                    return match.group(0)
                url = replacement_urls[idx]
                idx += 1
                return f'image:\n        "{_escape_js(url)}"'

            updated_block = re.sub(
                r'image:\s*\n\s*".*?"',
                _replace_image,
                block,
                count=3,
            )

            home_content = (
                home_content[:discovery_match.start(2)]
                + updated_block
                + home_content[discovery_match.end(2):]
            )

            with open(home_path, 'w', encoding='utf-8') as f:
                f.write(home_content)
