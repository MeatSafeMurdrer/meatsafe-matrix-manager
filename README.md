![Meatsafe Matrix Manager Banner](assets/meatsafe-matrix-manager.jpeg)



# Meatsafe's Matrix Manager for Draw Things

An interactive, terminal-based automation tool for the Draw Things macOS app. This script utilizes the Draw Things Local HTTP API to generate X/Y comparison matrices, allowing you to systematically test different Models, LoRAs, CFG scales, and step counts. 

Instead of manually swapping models and tweaking settings to find the perfect generation parameters, this manager automates the entire batch and outputs a neatly organized HTML spreadsheet and a master PNG grid of your results.

## See example matrices at the bottom.


## Features
* **Axis-Based Matrix Generation:** Choose any two variables to map across the X and Y axes.
* **Auto-Discovery:** Automatically scans and indexes your locally available base models and LoRAs.
* **Smart Filtering:** Only displays LoRAs compatible with your currently selected base model.
* **Parameter Backups:** Save and load your exact matrix configurations (models, prompts, steps, seeds, etc.) for repeatable testing.
* **Flexible Export Options:** Toggle exports for individual PNGs, a master grid PNG, and an HTML grid with prompt metadata.
* **Unhooked from the CLI:** Uses the local HTTP API to reliably manage heavy models without timing out.

## Pro-Tips for Complex Matrices

* **Dynamic Per-Model Steps:** Not all models require the same step count. If you are varying models on one axis (and leaving steps constant on the other), the manager will intelligently prompt you to enter a specific step count for *each individual model* you selected, or let you default to the model's native setting.
* **Universal vs. Varied LoRAs:** When configuring LoRAs, you have two options. **Varied LoRAs** will map to specific columns/rows on your matrix to compare their effects. **Universal LoRAs** (like a turbo or detailer LoRA) will be applied to *every* generation in the matrix, provided they are compatible with the base model for that specific cell.


## Installation for macOS

1. **Download the Repository:**
   Clone this repository via terminal or click "Code" -> "Download ZIP" and extract it to your preferred location.

2. **Run the Installer/Launcher:**
   * Open your `meatsafe-matrix-manager` folder.
   * Right-click `launch_matrix.command`, hold the `Option` key, and click **Open** (this bypasses the standard macOS unrecognized developer warning for the first run). 
   * The script will automatically build a Python virtual environment, install the required dependencies (`requests`, `Pillow`), and launch the dashboard.
   * *For all future uses, you can simply double-click `launch_matrix.command` to start the manager.*

3. **Configure Draw Things:**
   * Open Draw Things.
   * Go to **Settings** and check **Enable API Server** (HTTP, Port 7860).

## Roadmap / Coming Soon
This is v1.0. Future updates are planned to include:
* Varied LoRA strength testing.
* Full ControlNet profile integration.
* Additional axis variables, including Seed and Sampler comparisons.

---

### Support the Project
Is my code saving hours of time and frustration for you? Consider tipping me a couple of schmeckles! 

☕ [https://ko-fi.com/meatsafe](https://ko-fi.com/meatsafe)


## Example Images

![Example Matrix Output](assets/example1.png)
![Example Matrix Output](assets/example2.png)
![Example Matrix Output](assets/example3.png)
