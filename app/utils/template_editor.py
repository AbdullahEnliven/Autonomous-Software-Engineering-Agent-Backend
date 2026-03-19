import os
import shutil
import json
import re


def _escape_js(value: str) -> str:
    return value.replace('"', '\\"') if isinstance(value, str) else value

def create_project_from_template(base_dir: str, template_name: str, target_dir: str, config: dict):
    """
    Clones the template directory and injects the project-specific config.
    base_dir should be the root ASEA folder.
    """
    template_path = os.path.join(base_dir, template_name)

    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)

    # Copy all files
    shutil.copytree(template_path, target_dir)

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
    _update_home_splash(target_dir, normalized_config)

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

