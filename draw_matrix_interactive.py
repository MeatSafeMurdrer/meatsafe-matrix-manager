#!/usr/bin/env python3
import json
import os
import copy
import base64
import subprocess
import html
import textwrap
import io
import re
import urllib.request
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

MODELS_FILE = "matrix_models.json"
CONTROLS_FILE = "matrix_controls.json"
EXPORT_SETTINGS_FILE = "matrix_export_settings.json"
BACKUPS_FILE = "matrix_backups.json"
API_URL = "http://127.0.0.1:7860"

# ANSI Color Codes
CYAN = '\033[96m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BOLD = '\033[1m'
RESET = '\033[0m'

def clear_screen():
    os.system('clear' if os.name != 'nt' else 'cls')

# =======================================================================
# UTILITY HELPERS
# =======================================================================

def load_json(filepath, default_val):
    if not os.path.exists(filepath):
        return default_val
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return default_val

def load_models():
    raw = load_json(MODELS_FILE, [])
    for m in raw:
        if "source" not in m:
            m["source"] = "auto"
    return raw

def load_backups():
    raw = load_json(BACKUPS_FILE, [])
    if not isinstance(raw, list):
        return []
    # Sort chronologically (oldest at the top, newest at the bottom)
    return sorted(raw, key=lambda b: b.get("timestamp", ""))

def save_backups(backups):
    return save_json(BACKUPS_FILE, backups)

def get_backup_state(backup):
    if "state" in backup and isinstance(backup["state"], dict):
        return copy.deepcopy(backup["state"])
    state_keys = [
        "x_axis", "y_axis", "model", "prompt", "negative_prompt",
        "steps", "width", "height", "cfg_scale", "universal_loras",
        "varied_loras", "varied_lora_labels", "seed"
    ]
    st = {}
    for k in state_keys:
        if k in backup:
            st[k] = copy.deepcopy(backup[k])
    return st

def save_json(filepath, data):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"Error writing to {filepath}: {e}")
        return False

# Global Export Configuration
DEFAULT_EXPORT_SETTINGS = {
    "save_individual_pngs": True,
    "save_grid_png": True,
    "save_grid_html": True
}
EXPORT_SETTINGS = load_json(EXPORT_SETTINGS_FILE, DEFAULT_EXPORT_SETTINGS.copy())
for _k, _v in DEFAULT_EXPORT_SETTINGS.items():
    if _k not in EXPORT_SETTINGS:
        EXPORT_SETTINGS[_k] = _v

def prompt_menu(title, options, allow_multiple=False, allow_none=False, return_string=False):
    clear_screen()
    print(f"{CYAN}=== {title} ==={RESET}")
    print()
    for i, opt in enumerate(options):
        print(f"{i+1}. {opt}")
    print()
    
    while True:
        if allow_multiple:
            prompt_str = f"{YELLOW}Select options (comma-separated, e.g. 1,3) or 'all' (Press Enter for None): {RESET}"
        else:
            prompt_str = f"{YELLOW}Select an option number" + (" (Press Enter for None): " if allow_none else ": ") + f"{RESET}"
            
        choice = input(prompt_str).strip().lower()
        if not choice:
            if allow_none or allow_multiple:
                return [] if allow_multiple else None
            
        if allow_multiple:
            if choice == 'all':
                return [options[i] if return_string else i for i in range(len(options))]
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip()]
                if all(0 <= i < len(options) for i in indices):
                    return [options[i] if return_string else i for i in indices]
            except:
                pass
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    return options[idx] if return_string else idx
            except:
                pass
        print(f"{RED}Invalid choice, please try again.{RESET}")

def input_with_default(prompt_text, default_val):
    val = input(f"{YELLOW}{prompt_text.strip()} [{default_val}]: {RESET}").strip()
    return val if val else default_val

# =======================================================================
# API CLIENT
# =======================================================================

def get_api(endpoint):
    url = f"{API_URL}{endpoint}"
    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"{RED}❌ API Error querying {endpoint}: {e}{RESET}")
        print(f"{YELLOW}Make sure Draw Things is running and 'API Server' is enabled in its settings!{RESET}")
        return None

def post_api(endpoint, payload, timeout=1200):
    url = f"{API_URL}{endpoint}"
    data = json.dumps(payload).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode()
        print(f"{RED}❌ API Error ({e.code}): {error_msg}{RESET}")
        return None
    except Exception as e:
        print(f"{RED}❌ API Request Failed: {e}{RESET}")
        return None

def encode_image(filepath):
    if not filepath or not os.path.exists(filepath):
        return None
    with open(filepath, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# =======================================================================
# MANAGER: MODELS
# =======================================================================

def auto_discover_models(current_models=None):
    clear_screen()
    if current_models is None:
        current_models = load_models()
        
    print(f"{CYAN}--- Auto-Discover Local Models ---{RESET}")
    print()
    print("Scanning directories for local models...")
    # Only clear models with source == 'auto'. Preserve 'manual' and 'cloud'.
    preserved_models = [m for m in current_models if m.get("source") in ["manual", "cloud"]]
    
    dirs = [
        os.path.expanduser("~/Library/Containers/com.liuliu.draw-things/Data/Documents/Models"),
        os.path.expanduser("~/Library/Containers/Draw Things/Data/Documents/Models"),
        "/Volumes/Sabrent/Models",
        os.path.expanduser("~/AI/Models")
    ]
    
    master_models = {}
    
    # 1. Read custom.json from all accessible directories
    for d in dirs:
        c_path = os.path.join(d, "custom.json")
        if os.path.exists(c_path):
            try:
                with open(c_path) as f:
                    cdata = json.load(f)
                for m in cdata:
                    if m.get("file"):
                        master_models[m["file"]] = m.get("name", m["file"])
            except Exception:
                pass
            
    # 2. Read official downloaded models via draw-things-cli
    for d in dirs:
        if not os.path.exists(d):
            continue
        cmd = ["draw-things-cli", "models", "list", "--downloaded-only"]
        if d != os.path.expanduser("~/Library/Containers/com.liuliu.draw-things/Data/Documents/Models"):
            cmd.extend(["--models-dir", d])
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8")
            for line in output.split("\n"):
                line = line.strip()
                if line and not line.startswith("---") and not line.startswith("MODEL") and not line.startswith("Models directory"):
                    parts = [p.strip() for p in line.split("  ") if p.strip()]
                    if len(parts) >= 2:
                        master_models[parts[0]] = parts[1]
        except Exception:
            pass
            
    # 3. Only keep models where the file physically exists on disk right now
    found_models = []
    seen_files = set()
    for d in dirs:
        if not os.path.exists(d): continue
        for root, _, files in os.walk(d):
            for f in files:
                if f in master_models and f not in seen_files:
                    found_models.append({"name": master_models[f], "file": f, "source": "auto"})
                    seen_files.add(f)
                        
    existing_files = {m.get("file") for m in preserved_models}
    existing_names = {m.get("name") for m in preserved_models}
    
    new_auto_models = []
    for m in found_models:
        if m["file"] not in existing_files and m["name"] not in existing_names:
            new_auto_models.append(m)
            existing_files.add(m["file"])
            existing_names.add(m["name"])
            
    combined = preserved_models + new_auto_models
    save_json(MODELS_FILE, combined)
    print()
    print(f"{GREEN}Discovered {len(new_auto_models)} local base models (Preserved {len(preserved_models)} manual/cloud models):{RESET}")
    for m in combined:
        print(f"  • {m['name']} ({m['file']}) [{m.get('source', 'auto')}]")
    print()
    print(f"{GREEN}Models cache updated successfully!{RESET}")
    input(f"\n{YELLOW}Press Enter to return to Model Manager...{RESET}")
    return combined

def get_custom_models_dict():
    dirs = [
        os.path.expanduser("~/Library/Containers/com.liuliu.draw-things/Data/Documents/Models"),
        os.path.expanduser("~/Library/Containers/Draw Things/Data/Documents/Models"),
        "/Volumes/Sabrent/Models",
        os.path.expanduser("~/AI/Models")
    ]
    custom_models = {}
    for d in dirs:
        c_path = os.path.join(d, "custom.json")
        if os.path.exists(c_path):
            try:
                with open(c_path) as f:
                    for m in json.load(f):
                        if m.get("file"):
                            custom_models[m["file"]] = m
            except Exception:
                pass
    return custom_models

def get_model_version(model_file, custom_models_dict=None):
    if custom_models_dict is None:
        custom_models_dict = get_custom_models_dict()
    base = os.path.basename(model_file)
    if base in custom_models_dict and custom_models_dict[base].get("version"):
        return custom_models_dict[base]["version"]
    if model_file in custom_models_dict and custom_models_dict[model_file].get("version"):
        return custom_models_dict[model_file]["version"]
    f_lower = base.lower()
    if "flux_2_klein" in f_lower or "flux2_klein" in f_lower: return "flux2_4b"
    if "flux_2" in f_lower or "flux2" in f_lower: return "flux2"
    if "flux_1" in f_lower or "flux1" in f_lower or "schnell" in f_lower: return "flux1"
    if "z_image" in f_lower: return "z_image"
    if "sd3" in f_lower: return "sd3"
    if "sd_xl" in f_lower or "sdxl" in f_lower or "juggernaut_xl" in f_lower: return "sdxl_base_v0.9"
    if "krea_2" in f_lower or "krea2" in f_lower: return "krea_2"
    if "ltx" in f_lower: return "ltx2.3"
    if "sd_v1.5" in f_lower or "v1-5" in f_lower or "v1.5" in f_lower: return "v1"
    if "juggernaut_reborn" in f_lower: return "v1"
    return ""

def is_lora_compatible(lora_version, model_version):
    if not lora_version or not model_version:
        return True
    return lora_version == model_version

def get_model_display_name(model_file, saved_models=None):
    if not model_file:
        return "Unknown Model"
    base = os.path.basename(model_file)
    if saved_models:
        for m in saved_models:
            if m.get("file") == model_file or os.path.basename(m.get("file", "")) == base:
                return m.get("name", base)
    custom_dict = get_custom_models_dict()
    if base in custom_dict and custom_dict[base].get("name"):
        return custom_dict[base]["name"]
    return base

def get_lora_display_name(lora, all_loras_dict=None):
    if isinstance(lora, dict):
        if lora.get("name"):
            return lora["name"]
        f = lora.get("file")
        if f:
            if all_loras_dict is None:
                all_l = get_all_loras()
                all_loras_dict = {x["file"]: x for x in all_l if "file" in x}
            if f in all_loras_dict and all_loras_dict[f].get("name"):
                return all_loras_dict[f]["name"]
            base = os.path.basename(f)
            if base in all_loras_dict and all_loras_dict[base].get("name"):
                return all_loras_dict[base]["name"]
            return base
        return "Unknown LoRA"
    return str(lora)

def get_lora_version(lora, all_loras_dict=None):
    if isinstance(lora, dict):
        v = lora.get("version")
        if v:
            return v
        f = lora.get("file")
        if f:
            if all_loras_dict is None:
                all_l = get_all_loras()
                all_loras_dict = {x["file"]: x for x in all_l if "file" in x}
            if f in all_loras_dict and all_loras_dict[f].get("version"):
                return all_loras_dict[f]["version"]
            base = os.path.basename(f)
            if base in all_loras_dict and all_loras_dict[base].get("version"):
                return all_loras_dict[base]["version"]
    return ""

def get_all_loras():
    dirs = [
        os.path.expanduser("~/Library/Containers/com.liuliu.draw-things/Data/Documents/Models"),
        os.path.expanduser("~/Library/Containers/Draw Things/Data/Documents/Models"),
        "/Volumes/Sabrent/Models",
        os.path.expanduser("~/AI/Models")
    ]
    loras = []
    seen_files = set()
    for d in dirs:
        lp = os.path.join(d, "custom_lora.json")
        if os.path.exists(lp):
            try:
                with open(lp) as f:
                    ldata = json.load(f)
                for l in ldata:
                    f_name = l.get("file")
                    if f_name and f_name not in seen_files:
                        loras.append({
                            "name": l.get("name", f_name),
                            "file": f_name,
                            "prefix": l.get("prefix", ""),
                            "version": l.get("version", "")
                        })
                        seen_files.add(f_name)
            except Exception:
                pass
    return loras

def select_compatible_loras(chosen_models, allow_multiple=True, allow_none=True, prompt_title="Select LoRAs"):
    all_loras = get_all_loras()
    if not all_loras:
        print(f"\n{RED}No LoRAs found in custom_lora.json.{RESET}")
        return [] if allow_multiple else None
    custom_models_dict = get_custom_models_dict()
    
    # Group by model
    displayed_loras = []
    seen_files = set()
    groups = []
    for m in chosen_models:
        m_ver = get_model_version(m["file"], custom_models_dict)
        comp_loras = []
        for l in all_loras:
            if l["file"] not in seen_files and is_lora_compatible(l.get("version"), m_ver):
                comp_loras.append(l)
                seen_files.add(l["file"])
        if comp_loras:
            groups.append((m["name"], comp_loras))
            
    if not groups:
        print(f"\n{YELLOW}(No compatible LoRAs found for the selected model(s)){RESET}")
        return [] if allow_multiple else None
        
    clear_screen()
    print(f"{CYAN}=== {prompt_title} ==={RESET}")
    print()
    current_idx = 1
    for model_name, loras in groups:
        print(f"{CYAN}--- LoRAs compatible with {model_name} ---{RESET}")
        for l in loras:
            displayed_loras.append(l)
            prefix_str = f" [prefix: {l['prefix']}]" if l.get('prefix') else ""
            print(f"{current_idx}. {l['name']}{prefix_str}")
            current_idx += 1
        print()
            
    while True:
        if allow_multiple:
            prompt_str = f"{YELLOW}Select options (comma-separated, e.g. 1,3) or 'all' (Press Enter for None): {RESET}"
        else:
            prompt_str = f"{YELLOW}Select an option number" + (" (Press Enter for None): " if allow_none else ": ") + f"{RESET}"
            
        choice = input(prompt_str).strip().lower()
        if not choice:
            if allow_none or allow_multiple:
                return [] if allow_multiple else None
        if allow_multiple:
            if choice == 'all':
                return displayed_loras
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip()]
                if all(0 <= i < len(displayed_loras) for i in indices):
                    return [displayed_loras[i] for i in indices]
            except Exception:
                pass
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(displayed_loras):
                    return displayed_loras[idx]
            except Exception:
                pass
        print(f"{RED}Invalid choice, please try again.{RESET}")

def edit_models_manually(models):
    while True:
        clear_screen()
        print(f"{CYAN}--- Edit Model List Manually ---{RESET}")
        print()
        if not models:
            print("No models currently configured.")
        else:
            for i, m in enumerate(models):
                print(f"[{i+1}] {m['name']}")
        print()
        print("Options:")
        print("1. Add a model")
        print("2. Remove a model")
        print("3. Clear list")
        print("4. Return to Model Manager")
        print()
        choice = input(f"{YELLOW}Select an option: {RESET}").strip()
        
        if choice == '1':
            display_name = input(f"\n{YELLOW}Enter Display Name: {RESET}").strip()
            if not display_name:
                print(f"{RED}Display name cannot be empty.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                continue
            file_name = input(f"{YELLOW}Enter Exact Filename: {RESET}").strip()
            if not file_name:
                print(f"{RED}Filename cannot be empty.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                continue
            models.append({
                "name": display_name,
                "file": file_name,
                "source": "manual"
            })
            save_json(MODELS_FILE, models)
            print(f"\n{GREEN}Model successfully added!{RESET}")
            input(f"\n{YELLOW}Press Enter to continue...{RESET}")
            
        elif choice == '2':
            if not models:
                print(f"\n{RED}No models currently saved.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                continue
            idx_str = input(f"\n{YELLOW}Enter the number of the model to remove (or press Enter to cancel): {RESET}").strip()
            if not idx_str:
                continue
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(models):
                    removed = models.pop(idx)
                    save_json(MODELS_FILE, models)
                    print(f"\n{GREEN}Removed {removed['name']}.{RESET}")
                    input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                else:
                    print(f"\n{RED}Invalid selection.{RESET}")
                    input(f"\n{YELLOW}Press Enter to continue...{RESET}")
            except Exception:
                print(f"\n{RED}Invalid number.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                
        elif choice == '3':
            confirm = input(f"\n{YELLOW}Are you sure you want to clear all models? (y/n) [n]: {RESET}").strip().lower()
            if confirm == 'y':
                models.clear()
                save_json(MODELS_FILE, models)
                print(f"\n{GREEN}All models cleared from list.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                
        elif choice == '4':
            break
        else:
            print(f"\n{RED}Invalid choice, please select 1, 2, 3, or 4.{RESET}")
            input(f"\n{YELLOW}Press Enter to continue...{RESET}")
            
    return models

def manage_models():
    models = load_models()
    
    while True:
        clear_screen()
        print(f"{CYAN}--- Model Manager ---{RESET}")
        print()
        if not models:
            print("No models currently configured.")
        else:
            for i, m in enumerate(models):
                print(f"[{i+1}] {m['name']}")
                
        print()
        print("Options:")
        print("1. Edit Model List manually")
        print("2. Auto-Discover local models")
        print("3. Return to Main Menu")
        print()
        choice = input(f"{YELLOW}Select an option: {RESET}").strip()
        
        if choice == '1':
            models = edit_models_manually(models)
        elif choice == '2':
            models = auto_discover_models(models)
        elif choice == '3':
            break
        else:
            print(f"\n{RED}Invalid choice, please select 1, 2, or 3.{RESET}")
            input(f"\n{YELLOW}Press Enter to continue...{RESET}")

# =======================================================================
# MANAGER: CONTROLNET PROFILES
# =======================================================================

CONTROL_TYPES = [
    "none", "custom", "depth", "canny", "scribble", "pose", "normal BAE", 
    "color", "lineart", "softedge", "segmentation", "inpaint", 
    "instruct pix2pix", "shuffle", "MLSD", "tile", "blur", 
    "low quality", "grey", "moodboard", "image"
]

def manage_controlnets():
    profiles = load_json(CONTROLS_FILE, {})
    
    while True:
        print("\n--- ControlNet Profile Manager ---")
        profile_names = list(profiles.keys())
        if not profile_names:
            print("No ControlNet profiles configured.")
        else:
            for i, p_name in enumerate(profile_names):
                print(f"[{i+1}] {p_name} ({len(profiles[p_name])} controls)")
                
        print("\nOptions:")
        print("1. Create new ControlNet Profile")
        print("2. Remove a Profile")
        print("3. Return to Main Menu")
        
        choice = input("Select an option: ").strip()
        
        if choice == '1':
            new_profile = []
            print("\n-- Building New Profile --")
            while True:
                model_name = input("Enter ControlNet model name (or press Enter to finish): ").strip()
                if not model_name:
                    break
                    
                c_type = prompt_menu("Select module/preprocessor (usually 'none' if you supply the processed image directly)", CONTROL_TYPES, return_string=True)
                
                # Handle images
                images_data = []
                if c_type == "moodboard":
                    print("Moodboard selected! You can enter multiple images.")
                    while True:
                        img_path = input("Enter absolute path to image (or press Enter if done with images): ").strip()
                        if not img_path:
                            if not images_data:
                                print("You must provide at least one image!")
                                continue
                            break
                        img_pct = input_with_default(f"Enter percentage weight for this image (0-100)", "100")
                        try:
                            images_data.append({"path": img_path, "pct": float(img_pct) / 100.0})
                        except:
                            images_data.append({"path": img_path, "pct": 1.0})
                else:
                    img_path = input("Enter absolute path to input image: ").strip()
                    images_data.append({"path": img_path, "pct": 1.0})
                    
                overall_weight = input_with_default("Enter overall ControlNet weight (0-150%)", "100")
                try:
                    w_val = float(overall_weight) / 100.0
                except:
                    w_val = 1.0
                    
                start_pct = input_with_default("Start percentage (0-100)", "0")
                end_pct = input_with_default("End percentage (0-100)", "100")
                try:
                    s_val = float(start_pct) / 100.0
                    e_val = float(end_pct) / 100.0
                except:
                    s_val, e_val = 0.0, 1.0
                
                for img_data in images_data:
                    final_weight = w_val * img_data["pct"]
                    
                    control_block = {
                        "model": model_name,
                        "image_path": img_data["path"],
                        "weight": final_weight,
                        "guidance_start": s_val,
                        "guidance_end": e_val,
                        "module": c_type
                    }
                    new_profile.append(control_block)
                
                print("Control added to profile.")
                
            if new_profile:
                p_name = input("\nEnter a name for this ControlNet Profile: ").strip()
                if p_name:
                    profiles[p_name] = new_profile
                    save_json(CONTROLS_FILE, profiles)
                    print(f"Saved profile '{p_name}'.")
                    
        elif choice == '2':
            if not profile_names: continue
            idx_str = input("Enter the number of the profile to remove: ").strip()
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(profile_names):
                    p_name = profile_names[idx]
                    del profiles[p_name]
                    save_json(CONTROLS_FILE, profiles)
                    print(f"Removed '{p_name}'.")
            except:
                print("Invalid number.")
                
        elif choice == '3':
            break

# =======================================================================
# GENERATOR WIZARD & DASHBOARD
# =======================================================================

AXIS_KEYS = ["none", "model", "lora", "steps", "cfg"]
AXIS_LABELS = {
    "none": "None",
    "model": "Model",
    "lora": "LoRA",
    "steps": "Steps",
    "cfg": "CFG Scale"
}

def choose_axes():
    options_x = [
        "None (Single value / No variation)",
        "Model",
        "LoRA",
        "Steps",
        "CFG Scale"
    ]
    key_map_x = ["none", "model", "lora", "steps", "cfg"]
    x_idx = prompt_menu("Select Variation for X Axis", options_x, allow_multiple=False, allow_none=False)
    x_type = key_map_x[x_idx]
    
    y_type = "none"
    if x_type != "none":
        options_y = ["None (Single value / No variation)"]
        key_map_y = ["none"]
        for k in ["model", "lora", "steps", "cfg"]:
            if k != x_type:
                options_y.append(AXIS_LABELS[k])
                key_map_y.append(k)
        y_idx = prompt_menu("Select Variation for Y Axis", options_y, allow_multiple=False, allow_none=False)
        y_type = key_map_y[y_idx]
        
    return x_type, y_type

def has_selected_model(state):
    m = state.get("model")
    if not m:
        return False
    if isinstance(m, list):
        return len(m) > 0
    if isinstance(m, dict):
        return bool(m.get("file"))
    return False

def get_chosen_models_list(state):
    m = state.get("model")
    if not m:
        return []
    if isinstance(m, list):
        return m
    return [m]

def render_dashboard(state):
    clear_screen()
    x_label = AXIS_LABELS.get(state["x_axis"], "None")
    y_label = AXIS_LABELS.get(state["y_axis"], "None")
    
    # Model display
    if state["x_axis"] == "model" or state["y_axis"] == "model":
        axis_name = "X" if state["x_axis"] == "model" else "Y"
        m_list = state["model"] if isinstance(state["model"], list) else []
        if len(m_list) >= 2:
            model_disp = f"[{len(m_list)} models selected]"
        elif len(m_list) == 1:
            model_disp = f"[{m_list[0]['name']}] {RED}(Need >= 2) *MANDATORY*{RESET}"
        else:
            model_disp = f"{RED}(None selected) *MANDATORY*{RESET}"
        model_line = f"1. Model (Varies on {axis_name})".ljust(32) + f"-> {model_disp}"
    else:
        m = state["model"]
        if m and isinstance(m, dict):
            model_disp = f"{m['name']}"
        else:
            model_disp = f"{RED}(None selected) *MANDATORY*{RESET}"
        model_line = "1. Model".ljust(32) + f"-> {model_disp}"
        
    # Prompt display
    p_disp = f'"{state["prompt"][:35]}..."' if len(state["prompt"]) > 35 else f'"{state["prompt"]}"'
    if not state["prompt"]:
        p_disp = f"{RED}(Not set) *MANDATORY*{RESET}"
    prompt_line = "2. Prompt".ljust(32) + f"-> {p_disp}"
    
    # Negative prompt
    np_disp = f'"{state["negative_prompt"][:35]}..."' if len(state["negative_prompt"]) > 35 else f'"{state["negative_prompt"]}"'
    if not state["negative_prompt"]:
        np_disp = "(None)"
    np_line = "3. Negative Prompt".ljust(32) + f"-> {np_disp}"
    
    has_model = has_selected_model(state)
    
    # Steps display
    if not has_model:
        steps_line = "4. Steps".ljust(32) + f"-> {YELLOW}(Locked - Select Model first){RESET}"
    elif state["x_axis"] == "steps" or state["y_axis"] == "steps":
        axis_name = "X" if state["x_axis"] == "steps" else "Y"
        s_list = state["steps"] if isinstance(state["steps"], list) else []
        s_disp = f"{s_list}" if len(s_list) >= 2 else f"{s_list} {RED}(Need >= 2) *MANDATORY*{RESET}"
        steps_line = f"4. Steps (Varies on {axis_name})".ljust(32) + f"-> {s_disp}"
    elif state["x_axis"] == "model" or state["y_axis"] == "model":
        if isinstance(state.get("steps"), dict) and state["steps"]:
            items = []
            chosen = get_chosen_models_list(state)
            for m in chosen:
                s_val = state["steps"].get(m["file"])
                s_txt = str(s_val) if s_val is not None else "default"
                short_name = m.get("name", os.path.basename(m.get("file", "")))
                if len(short_name) > 18:
                    short_name = short_name[:15] + "..."
                items.append(f"{short_name}: {s_txt}")
            s_disp = "[" + ", ".join(items) + "]"
        else:
            s_disp = "(Model default / Press 4 to configure per-model)"
        steps_line = "4. Steps (Per-Model)".ljust(32) + f"-> {s_disp}"
    else:
        s_disp = str(state["steps"]) if state["steps"] is not None else "(Model default)"
        steps_line = "4. Steps".ljust(32) + f"-> {s_disp}"
        
    # Dimensions
    dim_line = "5. Dimensions".ljust(32) + f"-> {state['width']}x{state['height']}"
    
    # CFG Scale
    if state["x_axis"] == "cfg" or state["y_axis"] == "cfg":
        axis_name = "X" if state["x_axis"] == "cfg" else "Y"
        c_list = state["cfg_scale"] if isinstance(state["cfg_scale"], list) else []
        c_disp = f"{c_list}" if len(c_list) >= 2 else f"{c_list} {RED}(Need >= 2) *MANDATORY*{RESET}"
        cfg_line = f"6. CFG Scale (Varies on {axis_name})".ljust(32) + f"-> {c_disp}"
    else:
        cfg_disp = str(state["cfg_scale"]) if state["cfg_scale"] is not None else "(Model default)"
        cfg_line = "6. CFG Scale".ljust(32) + f"-> {cfg_disp}"
    
    # LoRAs display
    if not has_model:
        lora_line = "7. LoRAs".ljust(32) + f"-> {YELLOW}(Locked - Select Model first){RESET}"
    else:
        if state["x_axis"] == "lora" or state["y_axis"] == "lora":
            axis_name = "X" if state["x_axis"] == "lora" else "Y"
            v_len = len(state["varied_loras"])
            u_len = len(state["universal_loras"])
            if v_len >= 2:
                l_disp = f"[{v_len} varied" + (f", {u_len} universal]" if u_len else "]")
            else:
                l_disp = f"[{v_len} varied] {RED}(Need >= 2) *MANDATORY*{RESET}"
            lora_line = f"7. LoRAs (Varies on {axis_name})".ljust(32) + f"-> {l_disp}"
        else:
            u_len = len(state["universal_loras"])
            l_disp = f"[{u_len} universal LoRAs]" if u_len else "(None)"
            lora_line = "7. LoRAs".ljust(32) + f"-> {l_disp}"
            
    # Seed
    s_disp = "-1 (Random)" if state["seed"] == -1 else str(state["seed"])
    seed_line = "8. Seed".ljust(32) + f"-> {s_disp}"
    
    print(f"{CYAN}================ Matrix Configuration ================{RESET}")
    print(f"Varying on X: [{x_label}] | Varying on Y: [{y_label}]")
    print("------------------------------------------------------")
    print()
    print(model_line)
    print(prompt_line)
    print(np_line)
    print(steps_line)
    print(dim_line)
    print(cfg_line)
    print(lora_line)
    print(seed_line)
    print()
    print("------------------------------------------------------")
    print("Press [1-8] to edit, [S] to Save Parameters, [B] to reconfigure axes, or [Enter] to START GENERATION.")

def generate_matrix_wizard(initial_state=None):
    models = load_models()
    if not models:
        print("\nNo models found in cache. Running auto-discovery...")
        models = auto_discover_models()
        if not models:
            print(f"{RED}No models available. Please ensure models are installed and accessible.{RESET}")
            return

    if initial_state is not None:
        state = copy.deepcopy(initial_state)
    else:
        # Step A: Initial Axis Definition
        x_type, y_type = choose_axes()
        
        state = {
            "x_axis": x_type,
            "y_axis": y_type,
            "model": None,
            "prompt": "A portrait of a cyberpunk hacker, highly detailed",
            "negative_prompt": "",
            "steps": [10, 20, 30] if (x_type == "steps" or y_type == "steps") else None,
            "width": 1024,
            "height": 1024,
            "cfg_scale": [1.0, 2.0, 3.5] if (x_type == "cfg" or y_type == "cfg") else None,
            "universal_loras": [],
            "varied_loras": [],
            "varied_lora_labels": [],
            "seed": -1
        }
        
        # If model is constant and only 1 model is cached, preselect it
        if x_type != "model" and y_type != "model" and len(models) == 1:
            state["model"] = models[0]
        
    # Step B: Interactive Settings Dashboard Loop
    while True:
        render_dashboard(state)
        action = input(f"\n{YELLOW}Action: {RESET}").strip().lower()
        
        if action == 'b':
            # Reconfigure axes
            new_x, new_y = choose_axes()
            state["x_axis"] = new_x
            state["y_axis"] = new_y
            # Re-adjust model format
            if new_x == "model" or new_y == "model":
                if state["model"] and isinstance(state["model"], dict):
                    state["model"] = [state["model"]]
                elif not state["model"]:
                    state["model"] = []
            else:
                if state["model"] and isinstance(state["model"], list):
                    state["model"] = state["model"][0] if state["model"] else None
            # Re-adjust steps format
            if new_x == "steps" or new_y == "steps":
                if not isinstance(state["steps"], list):
                    state["steps"] = [10, 20, 30]
            elif new_x == "model" or new_y == "model":
                if not isinstance(state["steps"], dict):
                    state["steps"] = None
            else:
                if isinstance(state["steps"], list):
                    state["steps"] = state["steps"][0] if state["steps"] else None
                elif isinstance(state["steps"], dict):
                    state["steps"] = None
            # Re-adjust cfg format
            if new_x == "cfg" or new_y == "cfg":
                if not isinstance(state["cfg_scale"], list):
                    state["cfg_scale"] = [1.0, 2.0, 3.5]
            else:
                if isinstance(state["cfg_scale"], list):
                    state["cfg_scale"] = state["cfg_scale"][0] if state["cfg_scale"] else None
            continue

        elif action == 's':
            # Save Parameter Backup
            name = input(f"\n{YELLOW}Enter a name for this backup: {RESET}").strip()
            if not name:
                name = f"Backup {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
            backups = load_backups()
            new_backup = {
                "backup_name": name,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "state": copy.deepcopy(state),
                **copy.deepcopy(state)
            }
            backups.append(new_backup)
            if save_backups(backups):
                print(f"\n{GREEN}✅ Parameter backup saved!{RESET}")
            else:
                print(f"\n{RED}❌ Failed to save parameter backup.{RESET}")
            input(f"\n{YELLOW}Press Enter to continue...{RESET}")
            continue
            
        elif action == '':
            # Validate and start generation
            errors = []
            # 1. Model Validation
            if state["x_axis"] == "model" or state["y_axis"] == "model":
                axis_name = "X" if state["x_axis"] == "model" else "Y"
                m_list = state["model"] if isinstance(state["model"], list) else []
                if len(m_list) < 2:
                    errors.append(f"Model is set to vary on {axis_name} Axis, but fewer than 2 models are selected.")
            else:
                if not state["model"]:
                    errors.append("Please select a Base Model (Option 1).")
                    
            # 2. Prompt Validation
            if not state["prompt"] or not state["prompt"].strip():
                errors.append("Prompt cannot be empty (Option 2).")
                
            # 3. Varied Axes Validation
            for axis_var, axis_name in [(state["x_axis"], "X"), (state["y_axis"], "Y")]:
                if axis_var == "steps":
                    s_list = state["steps"] if isinstance(state["steps"], list) else []
                    if len(s_list) < 2:
                        errors.append(f"Steps is set to vary on {axis_name} Axis, but fewer than 2 step counts are configured (Option 4).")
                elif axis_var == "cfg":
                    c_list = state["cfg_scale"] if isinstance(state["cfg_scale"], list) else []
                    if len(c_list) < 2:
                        errors.append(f"CFG Scale is set to vary on {axis_name} Axis, but fewer than 2 CFG values are configured (Option 6).")
                elif axis_var == "lora":
                    if len(state["varied_loras"]) < 2:
                        errors.append(f"LoRA is set to vary on {axis_name} Axis, but fewer than 2 LoRA options are configured (Option 7).")
                        
            if errors:
                print(f"\n{RED}❌ Cannot start generation due to configuration errors:{RESET}")
                for err in errors:
                    print(f"  • {err}")
                input(f"\n{YELLOW}Press Enter to return to Dashboard...{RESET}")
                continue
            else:
                # Validation passed! Assemble and run matrix
                base_model_file = state["model"]["file"] if isinstance(state["model"], dict) else state["model"][0]["file"]
                BASE_CONFIG = {
                    "model": base_model_file,
                    "prompt": state["prompt"],
                    "negative_prompt": state["negative_prompt"],
                    "width": state["width"],
                    "height": state["height"],
                    "steps": state["steps"] if not (state["x_axis"] == "steps" or state["y_axis"] == "steps") else None,
                    "cfg_scale": state["cfg_scale"] if not (state["x_axis"] == "cfg" or state["y_axis"] == "cfg") else None,
                    "seed": state["seed"],
                    "loras": state["universal_loras"]
                }
                
                def build_axis_dict(axis_type):
                    if axis_type == "none":
                        return None
                    elif axis_type == "model":
                        return {
                            "type": "model",
                            "name": "Model",
                            "values": [m["file"] for m in state["model"]],
                            "labels": [m["name"] for m in state["model"]]
                        }
                    elif axis_type == "steps":
                        return {
                            "type": "steps",
                            "name": "Steps",
                            "values": state["steps"],
                            "labels": [f"{s} Steps" for s in state["steps"]]
                        }
                    elif axis_type == "cfg":
                        return {
                            "type": "cfg_scale",
                            "name": "CFG",
                            "values": state["cfg_scale"],
                            "labels": [f"CFG {c}" for c in state["cfg_scale"]]
                        }
                    elif axis_type == "lora":
                        return {
                            "type": "lora",
                            "name": "LoRA",
                            "values": state["varied_loras"],
                            "labels": state["varied_lora_labels"]
                        }
                    return None
                    
                X_AXIS = build_axis_dict(state["x_axis"])
                Y_AXIS = build_axis_dict(state["y_axis"])
                
                run_matrix(BASE_CONFIG, X_AXIS, Y_AXIS)
                break

        elif action == '1':
            # Edit Model
            models = load_models()
            if not models:
                print("\nNo models found in cache. Running auto-discovery...")
                models = auto_discover_models()
                if not models:
                    input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                    continue
            model_opts = [f"{m['name']} ({m['file']})" for m in models]
            if state["x_axis"] == "model" or state["y_axis"] == "model":
                axis_name = "X" if state["x_axis"] == "model" else "Y"
                indices = prompt_menu(f"Select 2 or more Models to vary on the {axis_name} Axis (comma-separated)", model_opts, allow_multiple=True)
                if indices:
                    state["model"] = [models[i] for i in indices]
                    if isinstance(state.get("steps"), dict):
                        old_steps = state["steps"]
                        state["steps"] = {m["file"]: old_steps.get(m["file"]) for m in state["model"]}
            else:
                idx = prompt_menu("Select Base Model", model_opts, allow_multiple=False)
                if idx is not None:
                    state["model"] = models[idx]

        elif action == '2':
            # Edit Prompt (Multi-line loop to bypass OS MAX_CANON limit)
            print(f"\n{YELLOW}Enter your prompt (Press Enter twice to finish):{RESET}")
            lines = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if not line:
                    break
                lines.append(line.strip())
            p = " ".join(lines).strip()
            if p:
                state["prompt"] = p

        elif action == '3':
            # Edit Negative Prompt (Multi-line loop to bypass OS MAX_CANON limit)
            print(f"\n{YELLOW}Enter your negative prompt (Press Enter twice to finish):{RESET}")
            lines = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if not line:
                    break
                lines.append(line.strip())
            state["negative_prompt"] = " ".join(lines).strip()

        elif action == '4':
            # Edit Steps (Dependency Locked until Model is selected)
            if not has_selected_model(state):
                print(f"\n{RED}Please select a base model first so steps can be configured.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                continue
                
            if state["x_axis"] == "steps" or state["y_axis"] == "steps":
                axis_name = "X" if state["x_axis"] == "steps" else "Y"
                cur = ", ".join(map(str, state["steps"])) if isinstance(state["steps"], list) else "10, 20, 30"
                val = input_with_default(f"Enter 2 or more step counts to vary on {axis_name} Axis (comma-separated)", cur)
                s_list = [int(s.strip()) for s in val.split(",") if s.strip().isdigit()]
                if s_list:
                    state["steps"] = s_list
            elif state["x_axis"] == "model" or state["y_axis"] == "model":
                # Dynamic Per-Model Steps
                chosen = get_chosen_models_list(state)
                if not chosen:
                    print(f"\n{RED}Please select models first (Option 1) so steps can be configured per model.{RESET}")
                    input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                    continue
                    
                print(f"\n{CYAN}--- Configure Steps per Model ---{RESET}")
                steps_dict = {}
                current_steps_dict = state["steps"] if isinstance(state.get("steps"), dict) else {}
                for m in chosen:
                    m_name = m.get("name", os.path.basename(m.get("file", "Model")))
                    m_file = m.get("file")
                    cur_val = current_steps_dict.get(m_file)
                    cur_disp = f" [current: {cur_val}]" if cur_val is not None else " [current: default]"
                    val = input(f"{YELLOW}Enter steps for {m_name} (Press Enter for default){cur_disp}: {RESET}").strip()
                    if not val:
                        steps_dict[m_file] = None
                    elif val.isdigit():
                        steps_dict[m_file] = int(val)
                    else:
                        print(f"{RED}Invalid number, using default.{RESET}")
                        steps_dict[m_file] = None
                state["steps"] = steps_dict
            else:
                cur_str = str(state["steps"]) if state["steps"] is not None else "model default"
                val = input(f"\n{YELLOW}Enter step count [Enter for model default steps] (current: {cur_str}): {RESET}").strip()
                if not val:
                    state["steps"] = None
                elif val.isdigit():
                    state["steps"] = int(val)

        elif action == '5':
            # Edit Dimensions
            w = input_with_default("Enter Width", str(state["width"]))
            h = input_with_default("Enter Height", str(state["height"]))
            if w.isdigit(): state["width"] = int(w)
            if h.isdigit(): state["height"] = int(h)

        elif action == '6':
            # Edit CFG Scale
            if state["x_axis"] == "cfg" or state["y_axis"] == "cfg":
                axis_name = "X" if state["x_axis"] == "cfg" else "Y"
                cur = ", ".join(map(str, state["cfg_scale"])) if isinstance(state["cfg_scale"], list) else "1.0, 2.0, 3.5"
                val = input_with_default(f"Enter 2 or more CFG scales to vary on {axis_name} Axis (comma-separated)", cur)
                try:
                    c_list = [float(s.strip()) for s in val.split(",") if s.strip()]
                    if c_list: state["cfg_scale"] = c_list
                except Exception:
                    print(f"{RED}Invalid input.{RESET}")
                    input(f"\n{YELLOW}Press Enter to continue...{RESET}")
            else:
                cur_str = str(state["cfg_scale"]) if state["cfg_scale"] is not None else "model default"
                val = input(f"\n{YELLOW}Enter CFG Scale [Enter for model default] (current: {cur_str}): {RESET}").strip()
                if not val:
                    state["cfg_scale"] = None
                else:
                    try:
                        state["cfg_scale"] = float(val)
                    except Exception:
                        print(f"{RED}Invalid number.{RESET}")
                        input(f"\n{YELLOW}Press Enter to continue...{RESET}")

        elif action == '7':
            # Edit LoRAs (Dependency Locked until Model is selected)
            if not has_selected_model(state):
                print(f"\n{RED}Please select a base model first so compatible items can be displayed.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                continue
            chosen_models = get_chosen_models_list(state)
            
            if state["x_axis"] == "lora" or state["y_axis"] == "lora":
                axis_name = "X" if state["x_axis"] == "lora" else "Y"
                while True:
                    clear_screen()
                    print(f"{CYAN}--- LoRA Configuration (Varies on {axis_name} Axis) ---{RESET}")
                    print()
                    print("1. Universal LoRAs (applied to every generation across all compatible models)")
                    print("2. Varied LoRAs (one unique LoRA per column/row)")
                    print("3. Return to Dashboard")
                    print()
                    sub_c = input(f"{YELLOW}Select an option: {RESET}").strip()
                    if sub_c == '1':
                        selected = select_compatible_loras(chosen_models, allow_multiple=True, prompt_title="Select Universal LoRAs")
                        if selected is not None:
                            state["universal_loras"] = selected
                    elif sub_c == '2':
                        selected = select_compatible_loras(chosen_models, allow_multiple=True, prompt_title=f"Select 2 or more LoRAs to vary on {axis_name} Axis")
                        if selected:
                            inc_none = input(f"\n{YELLOW}Include a 'No LoRA' baseline? (y/n) [y]: {RESET}").strip().lower() != 'n'
                            vals, labels = [], []
                            if inc_none:
                                vals.append([])
                                labels.append("No LoRA")
                            for l in selected:
                                vals.append([l])
                                labels.append(l["name"])
                            state["varied_loras"] = vals
                            state["varied_lora_labels"] = labels
                    elif sub_c == '3':
                        break
            else:
                selected = select_compatible_loras(chosen_models, allow_multiple=True, prompt_title="Select Universal LoRAs")
                if selected is not None:
                    state["universal_loras"] = selected

        elif action == '8':
            # Edit Seed
            cur_str = "-1 (Random)" if state["seed"] == -1 else str(state["seed"])
            val = input(f"\n{YELLOW}Enter Seed (0 to 4294967295) [Enter for default: -1 (Random)] (current: {cur_str}): {RESET}").strip()
            if not val:
                state["seed"] = -1
            else:
                try:
                    state["seed"] = int(val)
                except Exception:
                    print(f"{RED}Invalid seed number.{RESET}")
                    input(f"\n{YELLOW}Press Enter to continue...{RESET}")

def apply_axis(config, cell_loras, axis_type, value):
    if value is None: return
    if axis_type == "lora":
        if isinstance(value, list): cell_loras.extend(value)
        else: cell_loras.append(value)
    else:
        config[axis_type] = value

def build_api_payload(config, cell_loras):
    # Safety: always pass bare filename regardless of what's stored in the JSON
    model_filename = os.path.basename(config["model"])
    
    # Base A1111 Payload (Draw Things custom format)
    payload = {
        "model": model_filename,
        "prompt": config["prompt"],
        "negative_prompt": config.get("negative_prompt", ""),
        "seed": config.get("seed", -1),
        "width": config["width"],
        "height": config["height"]
    }
    
    if config.get("steps") is not None and not isinstance(config.get("steps"), dict):
        payload["steps"] = config["steps"]
        
    if config.get("cfg_scale") is not None:
        payload["cfg_scale"] = config["cfg_scale"]
    
    # Apply LoRAs to the root "loras" array with version compatibility check
    all_loras = config.get("loras", []) + cell_loras
    if all_loras:
        custom_models_dict = get_custom_models_dict()
        model_ver = get_model_version(model_filename, custom_models_dict)
        all_loras_list = get_all_loras()
        all_loras_dict = {l["file"]: l for l in all_loras_list if "file" in l}
        
        payload_loras = []
        for l in all_loras:
            if not l or not isinstance(l, dict):
                continue
            l_ver = get_lora_version(l, all_loras_dict)
            if l_ver and model_ver and l_ver != model_ver:
                continue
                
            lora_file = l.get("file")
            if not lora_file:
                continue
            
            payload_loras.append({
                "file": os.path.basename(lora_file),
                "weight": float(l.get("weight", 1.0))
            })
            
        if payload_loras:
            payload["loras"] = payload_loras
        
    return payload

def run_matrix(BASE_CONFIG, X_AXIS, Y_AXIS):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    OUTPUT_DIR = os.path.join("matrix_output", timestamp)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print(f"\nWriting all outputs to: {OUTPUT_DIR}/")
    
    x_values = X_AXIS["values"] if X_AXIS else [None]
    x_labels = X_AXIS["labels"] if X_AXIS else ["Default"]
    y_values = Y_AXIS["values"] if Y_AXIS else [None]
    y_labels = Y_AXIS["labels"] if Y_AXIS else ["Default"]
    
    saved_models = load_models()
    custom_models_dict = get_custom_models_dict()
    all_loras_list = get_all_loras()
    all_loras_dict = {l["file"]: l for l in all_loras_list if "file" in l}
    
    image_paths = {}
    pil_images = {}
    skipped_cells = set()
    
    for y_idx, y_val in enumerate(y_values):
        for x_idx, x_val in enumerate(x_values):
            cell_config = copy.deepcopy(BASE_CONFIG)
            cell_loras = []
            if X_AXIS: apply_axis(cell_config, cell_loras, X_AXIS["type"], x_val)
            if Y_AXIS: apply_axis(cell_config, cell_loras, Y_AXIS["type"], y_val)
            
            # Apply dynamic per-model steps if configured as a dictionary
            if isinstance(cell_config.get("steps"), dict):
                active_model_file = cell_config.get("model", "")
                step_val = cell_config["steps"].get(active_model_file)
                if step_val is None and active_model_file:
                    step_val = cell_config["steps"].get(os.path.basename(active_model_file))
                cell_config["steps"] = step_val
                
            model_file = cell_config.get("model", "")
            model_ver = get_model_version(model_file, custom_models_dict)
            model_name = get_model_display_name(model_file, saved_models)
            
            # 1. Compatibility Check for Varied LoRAs (On an Axis)
            incompatible_varied_lora = None
            for lora in cell_loras:
                lora_ver = get_lora_version(lora, all_loras_dict)
                if lora_ver and model_ver and lora_ver != model_ver:
                    incompatible_varied_lora = lora
                    break
                    
            if incompatible_varied_lora:
                lora_name = get_lora_display_name(incompatible_varied_lora, all_loras_dict)
                print(f"Cell [{x_idx+1}/{len(x_values)}, {y_idx+1}/{len(y_values)}] (X: {x_labels[x_idx]}, Y: {y_labels[y_idx]}):")
                print(f"{YELLOW}Skipping incompatible combination: {model_name} + {lora_name}.{RESET}")
                skipped_cells.add((x_idx, y_idx))
                image_paths[(x_idx, y_idx)] = None
                pil_images[(x_idx, y_idx)] = None
                continue
                
            # 2. Smart Universal LoRA Routing: filter out incompatible universal LoRAs without skipping cell
            compatible_universal = []
            for u_lora in cell_config.get("loras", []):
                u_ver = get_lora_version(u_lora, all_loras_dict)
                if u_ver and model_ver and u_ver != model_ver:
                    # Incompatible Universal LoRA: omit/drop it for this generation
                    continue
                compatible_universal.append(u_lora)
            cell_config["loras"] = compatible_universal
                
            out_path = os.path.join(OUTPUT_DIR, f"img_{x_idx}_{y_idx}.png")
            payload = build_api_payload(cell_config, cell_loras)
            
            print(f"Generating [{x_idx+1}/{len(x_values)}, {y_idx+1}/{len(y_values)}] (X: {x_labels[x_idx]}, Y: {y_labels[y_idx]})...")
            
            # Generate Image (timeout=1200 seconds / 20 minutes)
            response = post_api("/sdapi/v1/txt2img", payload, timeout=1200)
            if response and "images" in response and len(response["images"]) > 0:
                try:
                    img_bytes = base64.b64decode(response["images"][0])
                    cell_pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                    pil_images[(x_idx, y_idx)] = cell_pil
                    
                    if EXPORT_SETTINGS.get("save_individual_pngs", True):
                        cell_pil.save(out_path)
                        image_paths[(x_idx, y_idx)] = out_path
                        print(f"{GREEN}✅ Success (Saved individual PNG){RESET}")
                    else:
                        image_paths[(x_idx, y_idx)] = None
                        print(f"{GREEN}✅ Success{RESET}")
                except Exception as e:
                    print(f"{RED}❌ Failed to decode image: {e}{RESET}")
                    image_paths[(x_idx, y_idx)] = None
                    pil_images[(x_idx, y_idx)] = None
            else:
                print(f"{RED}❌ Generation failed via API.{RESET}")
                image_paths[(x_idx, y_idx)] = None
                pil_images[(x_idx, y_idx)] = None
                
    # --- Generate HTML Spreadsheet ---
    if EXPORT_SETTINGS.get("save_grid_html", True):
        html_path = os.path.join(OUTPUT_DIR, "grid.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html><html><head><meta charset='utf-8'>")
            f.write("<style>")
            f.write("body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 20px; background: #fafafa; color: #222; }")
            f.write(".header-box { background: #fff; padding: 20px; border-radius: 8px; border: 1px solid #ddd; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }")
            f.write(".header-box h2 { margin: 0 0 10px 0; color: #111; }")
            f.write(".header-box p { margin: 6px 0; font-size: 15px; }")
            f.write("table { border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }")
            f.write("th, td { border: 1px solid #e0e0e0; padding: 12px; text-align: center; vertical-align: middle; }")
            f.write("th { background-color: #f5f5f7; font-weight: 600; font-size: 14px; }")
            f.write("img { max-width: 512px; height: auto; border-radius: 6px; display: block; margin: 0 auto; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }")
            f.write(".failed { color: #888; font-style: italic; padding: 40px 20px; }")
            f.write(".blank { background: #fafafa; border: 1px solid #e0e0e0; min-width: 120px; min-height: 120px; }")
            f.write("</style></head><body>")
            
            # Injected Prompt text at the very top above matrix table
            f.write("<div class='header-box'>")
            f.write(f"<h2>Meatsafe's Matrix ({timestamp})</h2>")
            f.write(f"<p><b>Prompt:</b> {html.escape(BASE_CONFIG.get('prompt', ''))}</p>")
            if BASE_CONFIG.get("negative_prompt"):
                f.write(f"<p><b>Negative Prompt:</b> {html.escape(BASE_CONFIG['negative_prompt'])}</p>")
            f.write("</div>")
            
            f.write("<table><tr><th></th>")
            for x_l in x_labels:
                f.write(f"<th>{html.escape(str(x_l))}</th>")
            f.write("</tr>")
            for y_idx, y_l in enumerate(y_labels):
                f.write(f"<tr><th>{html.escape(str(y_l))}</th>")
                for x_idx, _ in enumerate(x_labels):
                    if (x_idx, y_idx) in skipped_cells:
                        f.write("<td class='blank'></td>")
                    else:
                        img_p = image_paths.get((x_idx, y_idx))
                        if img_p and os.path.exists(img_p):
                            f.write(f"<td><img src='{os.path.basename(img_p)}' /></td>")
                        else:
                            f.write("<td class='failed'>Failed / Not Saved</td>")
                f.write("</tr>")
            f.write("</table></body></html>")
        print(f"\n{GREEN}✅ HTML Spreadsheet saved to {html_path}{RESET}")

    # --- Generate Grid PNG ---
    if EXPORT_SETTINGS.get("save_grid_png", True):
        sample_img = next((img for img in pil_images.values() if img is not None), None)
        if sample_img is not None:
            cell_w, cell_h = sample_img.size
            x_count = len(x_values)
            y_count = len(y_values)
            
            # Setup fonts
            font_title = None
            font_header = None
            font_text = None
            system_fonts = [
                "/System/Library/Fonts/SFNS.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
                "/Library/Fonts/Arial.ttf"
            ]
            for fpath in system_fonts:
                if os.path.exists(fpath):
                    try:
                        font_title = ImageFont.truetype(fpath, 32)
                        font_header = ImageFont.truetype(fpath, 24)
                        font_text = ImageFont.truetype(fpath, 18)
                        break
                    except Exception:
                        pass
            if not font_title:
                font_title = ImageFont.load_default()
                font_header = ImageFont.load_default()
                font_text = ImageFont.load_default()
                
            has_y_axis = (Y_AXIS is not None)
            y_col_w = 220 if has_y_axis else 0
            
            prompt_text = f"Prompt: {BASE_CONFIG.get('prompt', '')}"
            total_img_width_approx = y_col_w + (cell_w * x_count)
            char_width_approx = 11
            max_chars = max(40, int((total_img_width_approx - 60) / char_width_approx))
            prompt_lines = textwrap.wrap(prompt_text, width=max_chars)
            if BASE_CONFIG.get("negative_prompt"):
                neg_lines = textwrap.wrap(f"Negative Prompt: {BASE_CONFIG['negative_prompt']}", width=max_chars)
                prompt_lines.extend(neg_lines)
                
            prompt_block_h = 50 + (len(prompt_lines) * 26) + 20
            col_header_h = 60
            top_header_h = prompt_block_h + col_header_h
            
            total_grid_w = y_col_w + (cell_w * x_count)
            total_grid_h = top_header_h + (cell_h * y_count)
            
            grid_img = Image.new("RGB", (total_grid_w, total_grid_h), color="#FFFFFF")
            draw = ImageDraw.Draw(grid_img)
            
            # 1. Draw Title
            draw.text((25, 20), f"Meatsafe's Matrix ({timestamp})", fill="#111111", font=font_title)
            
            # 2. Draw Prompt Lines
            curr_y = 65
            for line in prompt_lines:
                draw.text((25, curr_y), line, fill="#444444", font=font_text)
                curr_y += 26
                
            # 3. Draw Divider Line under prompt block
            draw.line([(0, prompt_block_h), (total_grid_w, prompt_block_h)], fill="#E0E0E0", width=2)
            
            # 4. Draw X Column Headers
            for x_idx, x_l in enumerate(x_labels):
                col_center_x = y_col_w + (x_idx * cell_w) + (cell_w // 2)
                col_y = prompt_block_h + (col_header_h // 2)
                try:
                    bbox = draw.textbbox((0, 0), str(x_l), font=font_header)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                except Exception:
                    tw, th = len(str(x_l)) * 10, 20
                draw.text((col_center_x - tw / 2, col_y - th / 2), str(x_l), fill="#111111", font=font_header)
                
            # 5. Draw Divider Lines
            draw.line([(0, top_header_h), (total_grid_w, top_header_h)], fill="#E0E0E0", width=2)
            if has_y_axis:
                draw.line([(y_col_w, prompt_block_h), (y_col_w, total_grid_h)], fill="#E0E0E0", width=2)
                
            # 6. Draw Y Row Headers and Paste Images
            for y_idx, y_l in enumerate(y_labels):
                row_center_y = top_header_h + (y_idx * cell_h) + (cell_h // 2)
                if has_y_axis:
                    try:
                        bbox = draw.textbbox((0, 0), str(y_l), font=font_header)
                        tw = bbox[2] - bbox[0]
                        th = bbox[3] - bbox[1]
                    except Exception:
                        tw, th = len(str(y_l)) * 10, 20
                    draw.text((y_col_w / 2 - tw / 2, row_center_y - th / 2), str(y_l), fill="#111111", font=font_header)
                    
                for x_idx in range(x_count):
                    paste_x = y_col_w + (x_idx * cell_w)
                    paste_y = top_header_h + (y_idx * cell_h)
                    if (x_idx, y_idx) in skipped_cells:
                        # Leave skipped cell completely blank (clean white background, no box or text)
                        draw.rectangle([paste_x, paste_y, paste_x + cell_w, paste_y + cell_h], fill="#FFFFFF", outline="#FFFFFF")
                    else:
                        cell_img = pil_images.get((x_idx, y_idx))
                        if cell_img is not None:
                            if cell_img.size != (cell_w, cell_h):
                                cell_img = cell_img.resize((cell_w, cell_h), Image.Resampling.LANCZOS)
                            grid_img.paste(cell_img, (paste_x, paste_y))
                        else:
                            draw.rectangle([paste_x, paste_y, paste_x + cell_w, paste_y + cell_h], fill="#F0F0F0", outline="#E0E0E0")
                            draw.text((paste_x + cell_w // 2 - 25, paste_y + cell_h // 2 - 10), "Failed", fill="#888888", font=font_header)
                        
            grid_out_path = os.path.join(OUTPUT_DIR, "grid.png")
            grid_img.save(grid_out_path)
            print(f"{GREEN}✅ Grid Image saved to {grid_out_path}{RESET}")
        else:
            print(f"{YELLOW}⚠️  No successful images were generated to stitch into grid.png.{RESET}")
            
    input(f"\n{YELLOW}Generation complete! Press Enter to return to main menu...{RESET}")

# =======================================================================
# MANAGER: PARAMETER BACKUPS
# =======================================================================

def manage_parameter_backups():
    while True:
        clear_screen()
        backups = load_backups()
        print(f"{CYAN}--- Parameter Backups ---{RESET}")
        print()
        if not backups:
            print("No backups saved.")
        else:
            for i, b in enumerate(backups):
                b_name = b.get("backup_name", f"Backup {i+1}")
                b_date = b.get("timestamp", "Unknown date")
                print(f"[{i+1}] {b_name} ({b_date})")
        print()
        print("Options:")
        print("1. Load a backup")
        print("2. Delete a backup")
        print("3. Return to Main Menu")
        print()
        choice = input(f"{YELLOW}Select an option: {RESET}").strip().lower()
        
        if choice == '1':
            if not backups:
                print(f"\n{RED}No backups available to load.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                continue
            idx_str = input(f"\n{YELLOW}Enter backup number to load [1-{len(backups)}]: {RESET}").strip()
            if idx_str.isdigit():
                idx = int(idx_str) - 1
                if 0 <= idx < len(backups):
                    selected_backup = backups[idx]
                    saved_state = get_backup_state(selected_backup)
                    generate_matrix_wizard(initial_state=saved_state)
                    return
                else:
                    print(f"\n{RED}Invalid backup number.{RESET}")
                    input(f"\n{YELLOW}Press Enter to continue...{RESET}")
            else:
                print(f"\n{RED}Invalid input.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                
        elif choice == '2':
            if not backups:
                print(f"\n{RED}No backups available to delete.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                continue
            idx_str = input(f"\n{YELLOW}Enter backup number to delete [1-{len(backups)}]: {RESET}").strip()
            if idx_str.isdigit():
                idx = int(idx_str) - 1
                if 0 <= idx < len(backups):
                    del backups[idx]
                    save_backups(backups)
                    print(f"\n{GREEN}✅ Backup deleted!{RESET}")
                    input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                else:
                    print(f"\n{RED}Invalid backup number.{RESET}")
                    input(f"\n{YELLOW}Press Enter to continue...{RESET}")
            else:
                print(f"\n{RED}Invalid input.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
                
        elif choice in ['3', 'b', 'return', 'exit', 'q']:
            break
        else:
            print(f"\n{RED}Invalid choice.{RESET}")
            input(f"\n{YELLOW}Press Enter to continue...{RESET}")

# =======================================================================
# MANAGER: EXPORT SETTINGS
# =======================================================================

def manage_export_settings():
    while True:
        clear_screen()
        print(f"{CYAN}=================================")
        print("        EXPORT SETTINGS")
        print(f"================================={RESET}")
        print()
        indiv_status = f"{GREEN}ENABLED{RESET}" if EXPORT_SETTINGS["save_individual_pngs"] else f"{RED}DISABLED{RESET}"
        grid_png_status = f"{GREEN}ENABLED{RESET}" if EXPORT_SETTINGS["save_grid_png"] else f"{RED}DISABLED{RESET}"
        grid_html_status = f"{GREEN}ENABLED{RESET}" if EXPORT_SETTINGS["save_grid_html"] else f"{RED}DISABLED{RESET}"
        
        print(f"1. Save Individual PNGs : [{indiv_status}]")
        print(f"2. Save Grid PNG        : [{grid_png_status}]")
        print(f"3. Save Grid HTML       : [{grid_html_status}]")
        print()
        print("Enter [1-3] to toggle, or [B] to go back to Main Menu.")
        print()
        choice = input(f"{YELLOW}Select an option: {RESET}").strip().lower()
        if choice == 'b':
            save_json(EXPORT_SETTINGS_FILE, EXPORT_SETTINGS)
            break
        elif choice == '1':
            EXPORT_SETTINGS["save_individual_pngs"] = not EXPORT_SETTINGS["save_individual_pngs"]
            if not EXPORT_SETTINGS["save_individual_pngs"] and EXPORT_SETTINGS["save_grid_html"]:
                EXPORT_SETTINGS["save_grid_html"] = False
                print(f"\n{YELLOW}ℹ️  Note: Disabling Individual PNGs also disabled Grid HTML, as local images are required for the HTML to render.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
            save_json(EXPORT_SETTINGS_FILE, EXPORT_SETTINGS)
        elif choice == '2':
            EXPORT_SETTINGS["save_grid_png"] = not EXPORT_SETTINGS["save_grid_png"]
            save_json(EXPORT_SETTINGS_FILE, EXPORT_SETTINGS)
        elif choice == '3':
            EXPORT_SETTINGS["save_grid_html"] = not EXPORT_SETTINGS["save_grid_html"]
            if EXPORT_SETTINGS["save_grid_html"] and not EXPORT_SETTINGS["save_individual_pngs"]:
                EXPORT_SETTINGS["save_individual_pngs"] = True
                print(f"\n{YELLOW}ℹ️  Note: Automatically enabled 'Save Individual PNGs' because local images are required for the HTML to render.{RESET}")
                input(f"\n{YELLOW}Press Enter to continue...{RESET}")
            save_json(EXPORT_SETTINGS_FILE, EXPORT_SETTINGS)
        else:
            print(f"\n{RED}Invalid choice, please select 1, 2, 3, or B.{RESET}")
            input(f"\n{YELLOW}Press Enter to continue...{RESET}")

# =======================================================================
# MAIN ENTRYPOINT
# =======================================================================

def main():
    if not os.path.exists(MODELS_FILE):
        clear_screen()
        print(f"{YELLOW}Welcome! No models found in {MODELS_FILE}.{RESET}")
        print("Let's fetch them from the Draw Things API first!")
        input(f"\n{YELLOW}Press Enter to continue...{RESET}")
        manage_models()
        
    while True:
        clear_screen()
        print(f"{CYAN}=================================")
        print("  Meatsafe's Matrix Manager v1.0")
        print(f"================================={RESET}")
        print()
        
        has_backups = len(load_backups()) > 0
        
        print("1. Generate a Matrix")
        print("2. Manage Base Models")
        if has_backups:
            print("3. Parameter Backups")
            print("4. Export Settings")
            print("5. Exit")
        else:
            print("3. Export Settings")
            print("4. Exit")
        print()
        choice = input(f"{YELLOW}Select an option: {RESET}").strip().lower()
        
        if choice == '1':
            generate_matrix_wizard()
        elif choice == '2':
            manage_models()
        elif has_backups and choice == '3':
            manage_parameter_backups()
        elif (has_backups and choice == '4') or (not has_backups and choice == '3'):
            manage_export_settings()
        elif (has_backups and choice in ['5', 'exit', 'q']) or (not has_backups and choice in ['4', 'exit', 'q']):
            clear_screen()
            print(f"{GREEN}Goodbye!{RESET}")
            break
        elif choice in ['exit', 'q']:
            clear_screen()
            print(f"{GREEN}Goodbye!{RESET}")
            break
        else:
            print(f"\n{RED}Invalid choice.{RESET}")
            input(f"\n{YELLOW}Press Enter to continue...{RESET}")

if __name__ == "__main__":
    main()
