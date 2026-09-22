#!/usr/bin/env python3
import subprocess
import json
import os
import copy
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# =======================================================================
# UTILITIES
# =======================================================================

def load_list_from_file(filepath):
    """Loads a list of strings from a text file, ignoring empty lines and comments."""
    if not os.path.exists(filepath):
        print(f"Warning: File not found: {filepath}. Returning empty list.")
        return []
    with open(filepath, 'r') as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return lines

def build_lora_list_from_names(lora_names, weight=1.0, version="flux1"):
    """
    Given a list of lora file names (e.g. from a text file), 
    builds the list of dictionaries required by the CLI.
    """
    return [[{"file": name, "weight": weight, "version": version}] for name in lora_names]

# =======================================================================
# CONFIGURATION
# =======================================================================

OUTPUT_DIR = "matrix_output"
OUTPUT_NAME = "grid" # Will generate grid.png and grid.html

# Base parameters for all generations. 
BASE_CONFIG = {
    "model": "flux_2_klein_4b_q6p.ckpt",
    "prompt": "A portrait of a cyberpunk hacker, highly detailed",
    "negative_prompt": "",
    "steps": 4,
    "cfg": 1,
    "width": 1024,
    "height": 1024,
    "seed": 12345, # Use a fixed seed for comparisons
}

# The axes of your grid. 
# You can define an X axis (columns) and a Y axis (rows).
# Set Y_AXIS to None if you only want a single row (1D grid).
# Supported types: "model", "lora", "steps", "cfg", "prompt", "seed", "strength"

# EXAMPLE 1: Using models from a list
# X_AXIS = {
#     "type": "model",
#     "name": "Model",
#     "values": [
#         "flux_2_klein_4b_q6p.ckpt",
#         "flux_2_klein_9b_q6p.ckpt"
#     ],
#     "labels": [
#         "Klein 4B",
#         "Klein 9B"
#     ]
# }

# EXAMPLE 2: Loading models from a text file (create models.txt with one model filename per line)
# model_list = load_list_from_file("models.txt")
# X_AXIS = {
#     "type": "model",
#     "name": "Model",
#     "values": model_list,
#     "labels": model_list # use filenames as labels
# }

# EXAMPLE 3: Mixing LoRAs (Combinations of 2 LoRAs)
# Create a text file `loras.txt` with your lora filenames.
# lora_names = load_list_from_file("loras.txt")
# lora_values = [[]] + build_lora_list_from_names(lora_names, weight=0.8) # Add an empty list for "No LoRA"
# lora_labels = ["No LoRA"] + lora_names
# X_AXIS = {"type": "lora", "name": "LoRA 1", "values": lora_values, "labels": lora_labels}
# Y_AXIS = {"type": "lora", "name": "LoRA 2", "values": lora_values, "labels": lora_labels}

# CURRENT ACTIVE SETUP (Modify this to your liking)
X_AXIS = {
    "type": "model",
    "name": "Model",
    "values": [
        "flux_2_klein_4b_q6p.ckpt",
        "flux_2_klein_9b_q6p.ckpt"
    ],
    "labels": [
        "Klein 4B",
        "Klein 9B"
    ]
}

Y_AXIS = {
    "type": "cfg",
    "name": "CFG Scale",
    "values": [1, 2],
    "labels": ["CFG 1", "CFG 2"]
}

# =======================================================================
# SCRIPT LOGIC
# =======================================================================

def apply_axis(config, loras, axis_type, value):
    if value is None:
        return
    if axis_type == "lora":
        if isinstance(value, list):
            loras.extend(value)
        else:
            loras.append(value)
    else:
        config[axis_type] = value

def build_command(config, loras, out_path):
    cmd = [
        "draw-things-cli", "generate",
        "--model", str(config["model"]),
        "--prompt", str(config["prompt"]),
        "--steps", str(config["steps"]),
        "--cfg", str(config["cfg"]),
        "--width", str(config["width"]),
        "--height", str(config["height"]),
        "--output", str(out_path)
    ]
    
    if "seed" in config and config["seed"] is not None:
        cmd.extend(["--seed", str(config["seed"])])
    if "negative_prompt" in config and config["negative_prompt"]:
        cmd.extend(["--negative-prompt", str(config["negative_prompt"])])
    if "strength" in config:
        cmd.extend(["--strength", str(config["strength"])])
        
    if loras:
        unique_loras = {}
        for l in loras:
            if l["file"] not in unique_loras:
                unique_loras[l["file"]] = l
        
        config_json = json.dumps({"loras": list(unique_loras.values())})
        cmd.extend(["--config-json", config_json])
        
    return cmd

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    x_values = X_AXIS["values"] if X_AXIS else [None]
    x_labels = X_AXIS["labels"] if X_AXIS else ["Default"]
    y_values = Y_AXIS["values"] if Y_AXIS else [None]
    y_labels = Y_AXIS["labels"] if Y_AXIS else ["Default"]
    
    x_len = len(x_values)
    y_len = len(y_values)
    
    print(f"Starting matrix generation: {x_len} x {y_len} = {x_len * y_len} images.")
    
    image_paths = {}
    
    for y_idx, y_val in enumerate(y_values):
        for x_idx, x_val in enumerate(x_values):
            cell_config = copy.deepcopy(BASE_CONFIG)
            cell_loras = []
            
            if X_AXIS:
                apply_axis(cell_config, cell_loras, X_AXIS["type"], x_val)
            if Y_AXIS:
                apply_axis(cell_config, cell_loras, Y_AXIS["type"], y_val)
                
            out_filename = f"img_{x_idx}_{y_idx}.png"
            out_path = os.path.join(OUTPUT_DIR, out_filename)
            
            cmd = build_command(cell_config, cell_loras, out_path)
            
            print(f"Generating [{x_idx},{y_idx}] (X: {x_labels[x_idx]}, Y: {y_labels[y_idx]})...")
            
            try:
                subprocess.run(cmd, check=True)
                image_paths[(x_idx, y_idx)] = out_path
            except subprocess.CalledProcessError as e:
                print(f"Error generating [{x_idx},{y_idx}]: {e}")
                image_paths[(x_idx, y_idx)] = None
                
    # --- Generate HTML Spreadsheet ---
    html_path = os.path.join(OUTPUT_DIR, f"{OUTPUT_NAME}.html")
    with open(html_path, "w") as f:
        f.write("<html><head><style>\n")
        f.write("table { border-collapse: collapse; font-family: sans-serif; }\n")
        f.write("th, td { border: 1px solid #ccc; padding: 10px; text-align: center; }\n")
        f.write("th { background-color: #f4f4f4; }\n")
        f.write("img { max-width: 512px; height: auto; }\n")
        f.write("</style></head><body>\n")
        f.write(f"<h2>Draw Things Matrix</h2>")
        f.write(f"<p><b>Base Prompt:</b> {BASE_CONFIG['prompt']}</p>")
        f.write("<table>\n")
        
        # Header row
        f.write("<tr><th></th>")
        for x_label in x_labels:
            f.write(f"<th>{x_label}</th>")
        f.write("</tr>\n")
        
        for y_idx, y_label in enumerate(y_labels):
            f.write(f"<tr><th>{y_label}</th>")
            for x_idx, x_label in enumerate(x_labels):
                img_path = image_paths.get((x_idx, y_idx))
                if img_path and os.path.exists(img_path):
                    f.write(f"<td><img src='{os.path.basename(img_path)}' /></td>")
                else:
                    f.write("<td><i>Failed</i></td>")
            f.write("</tr>\n")
        f.write("</table></body></html>\n")
    print(f"HTML Spreadsheet saved to {html_path}")
    
    # --- Generate Grid Image ---
    first_img_path = next((p for p in image_paths.values() if p and os.path.exists(p)), None)
    if first_img_path:
        with Image.open(first_img_path) as img:
            img_w, img_h = img.size
            
        header_h = 100
        row_label_w = 150 if Y_AXIS else 0
            
        grid_w = row_label_w + (img_w * x_len)
        grid_h = header_h + (img_h * y_len)
        
        grid_img = Image.new('RGB', (grid_w, grid_h), color='white')
        draw = ImageDraw.Draw(grid_img)
        
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
        except:
            font = ImageFont.load_default()
            
        for x_idx, x_label in enumerate(x_labels):
            text_x = row_label_w + x_idx * img_w + (img_w // 2)
            text_y = header_h // 2
            bbox = draw.textbbox((0,0), x_label, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            draw.text((text_x - w/2, text_y - h/2), x_label, fill='black', font=font)
            
        for y_idx, y_label in enumerate(y_labels):
            if Y_AXIS:
                text_x = row_label_w // 2
                text_y = header_h + y_idx * img_h + (img_h // 2)
                bbox = draw.textbbox((0,0), y_label, font=font)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
                draw.text((text_x - w/2, text_y - h/2), y_label, fill='black', font=font)
                
            for x_idx, _ in enumerate(x_labels):
                img_path = image_paths.get((x_idx, y_idx))
                if img_path and os.path.exists(img_path):
                    with Image.open(img_path) as cell_img:
                        cell_img = cell_img.resize((img_w, img_h))
                        paste_x = row_label_w + x_idx * img_w
                        paste_y = header_h + y_idx * img_h
                        grid_img.paste(cell_img, (paste_x, paste_y))
                        
        grid_out_path = os.path.join(OUTPUT_DIR, f"{OUTPUT_NAME}.png")
        grid_img.save(grid_out_path)
        print(f"Grid Image saved to {grid_out_path}")

if __name__ == "__main__":
    main()
