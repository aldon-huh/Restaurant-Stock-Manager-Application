"""
Restaurant Ingredient Tracker
=============================
A terminal app for restaurants to track ingredient stock, build a recipe book,
calculate dish costs, deduct sold dishes from stock, and generate supplier orders.

Data files (saved next to this script or the built executable):
    Inventory.csv             - ingredient stock levels, minimums, unit prices, suppliers
    recipes.json              - saved menu recipes
    Restaurant Inventory.db   - SQLite database holding saved reorder logs
"""
# Standard library imports
import json
import math
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
# Third-party libraries: pandas (data tables), rich (colored terminal output)
import pandas as pd

from rich import print
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table


# --- FILE LOCATION HELPERS ---
def resource_path(name):
    """Location of a file bundled inside the executable (or next to the script in dev)."""
    # sys._MEIPASS only exists inside a PyInstaller build; otherwise use the script's folder
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / name


def app_dir():
    """Folder where the app should keep its writable data files."""
    # 'frozen' is True when running as a built executable (so use the .exe's folder)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # Running as a normal Python script (so use the script's folder)
    return Path(__file__).parent


# --- DATA FILE LOCATIONS ---
# All data files are saved beside the script/executable, so the app finds them
# no matter which folder it was launched from.
DATA_DIR = app_dir()
CSV_FILE = str(DATA_DIR / "Inventory.csv")
DB_FILE = str(DATA_DIR / "Restaurant Inventory.db")
RECIPES_FILE = str(DATA_DIR / "recipes.json")
# Shared console used for all colored output
console = Console()


# --- INPUT VALIDATION ---
def parse_amount(text, allow_zero=True):
    """Converts text to a finite, non-negative float. Returns None if invalid."""
    # Reject anything that isn't a number
    try:
        value = float(str(text).strip())
    except ValueError:
        return None
    # Reject nan/inf, negative numbers, and (optionally) zero
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        return None
    return value


# --- INVENTORY & RECIPE FILE HANDLING ---
def invsampleCSV():
    """Seeds inventory from the bundled CSV, or a built-in sample if none was bundled."""
    # Only create an inventory file if one doesn't exist yet
    if not os.path.exists(CSV_FILE):
        # Prefer a starting inventory that was bundled into the executable
        bundled = resource_path("Inventory.csv")
        if bundled.exists():
            shutil.copy(bundled, CSV_FILE)
            console.print(f"[bold green]Created '{CSV_FILE}' from bundled inventory.[/bold green]")
            return

        # Otherwise fall back to a small built-in sample inventory
        sample_data = {
            "ingredient": ["Eggs", "Apples", "Olive Oil", "Chicken", "Rice", "Flour", "Mozzarella", "Tomatoes"],
            "current_stock": [40.0, 12.0, 4.0, 45.0, 10.0, 30.0, 8.0, 5.0],
            "min_required": [20.0, 6.0, 2.0, 20.0, 5.0, 15.0, 10.0, 8.0],
            "unit": ["ct", "ct", "bottles", "lbs", "lbs", "kg", "kg", "kg"],
            "unit_price": [0.25, 0.50, 8.00, 4.50, 1.20, 1.50, 6.00, 2.00],
            "supplier": ["Local Market", "Local Market", "Italian Imports", "Meat Direct", "Grain Co", "Grain Co", "Dairy Direct", "Local Market"],
        }
        pd.DataFrame(sample_data).to_csv(CSV_FILE, index=False)
        console.print(f"[bold green]Created sample '{CSV_FILE}' file with unit prices![/bold green]")


def load_inventory():
    """Loads and sanitizes inventory data from CSV."""
    # Make sure an inventory file exists before reading it
    invsampleCSV()
    try:
        df = pd.read_csv(CSV_FILE)
        # Remove stray spaces from column names
        df.columns = df.columns.str.strip()

        # Force numeric columns to float so fractional deductions work
        for col in ["current_stock", "min_required", "unit_price"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)

        return df
    # A bad or unreadable file shouldn't crash the app; callers check for None
    except Exception as e:
        console.print(f"[bold red]Could not load inventory file: {e}[/bold red]")
        return None


def load_recipes():
    """Loads saved recipes from JSON. Returns an empty dict if none exist yet."""
    # On first run, copy in a bundled recipe book if one was shipped with the app
    if not os.path.exists(RECIPES_FILE):
        bundled = resource_path("recipes.json")
        if bundled.exists():
            shutil.copy(bundled, RECIPES_FILE)

    # Read the saved recipes; unreadable or invalid files are ignored
    if os.path.exists(RECIPES_FILE):
        try:
            with open(RECIPES_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # No recipes yet: start blank. Recipes are added through menu option 5.
    return {}


def save_recipes(recipes):
    """Saves recipes dictionary to JSON file."""
    # Write the whole recipe book as readable, indented JSON
    with open(RECIPES_FILE, "w") as f:
        json.dump(recipes, f, indent=4)


# --- DYNAMIC RECIPE CREATION ---
def add_custom_recipe():
    """Allows staff to enter new menu items, selling price, and ingredient usage."""
    # Load the inventory so ingredient names can be matched against it
    df = load_inventory()
    if df is None:
        return

    # Load existing recipes (an empty book if there are none yet)
    recipes = load_recipes() or {}

    console.print(Panel("[bold green]ADD NEW MENU DISH & RECIPE[/bold green]", title="Recipe Builder"))
    # Step 1: name of the new dish
    dish_name = Prompt.ask("Enter new Dish / Menu Item name").strip()

    if not dish_name:
        console.print("[yellow]Dish name cannot be empty.[/yellow]")
        return

    # Step 2: selling price (an invalid entry falls back to $10.00)
    price_input = Prompt.ask(f"Selling price for {dish_name} ($)", default="10.00")
    selling_price = parse_amount(price_input)
    if selling_price is None:
        console.print("[yellow]Invalid price entered. Using default of $10.00.[/yellow]")
        selling_price = 10.00

    # Step 3: show the ingredient names that exist in the inventory
    available_ingredients = df["ingredient"].tolist()
    console.print(f"\n[cyan]Available ingredients in inventory:[/cyan] {', '.join(available_ingredients)}")

    # Step 4: add ingredients one at a time; press Enter on a blank name to finish
    recipe_ingredients = {}
    while True:
        ing_name = Prompt.ask("\nEnter ingredient name used (or press Enter to finish recipe)").strip()
        if not ing_name:
            break

        # Case-insensitive matching against inventory
        matched = [i for i in available_ingredients if i.lower() == ing_name.lower()]
        # Ingredients missing from the inventory are allowed, but flagged
        if not matched:
            console.print(f"[yellow]Warning: '{ing_name}' is not in your Inventory.csv yet.[/yellow]")
            real_name = ing_name
            unit = "units"
        else:
            real_name = matched[0]
            unit = df[df["ingredient"] == real_name]["unit"].values[0]

        # Quantity is per single dish, in the same unit the inventory uses
        qty_str = Prompt.ask(f"Quantity of '{real_name}' used per dish (in {unit})")
        qty = parse_amount(qty_str, allow_zero=False)
        if qty is None:
            console.print("[red]Invalid quantity (must be a number greater than 0). Skipping ingredient.[/red]")
        else:
            recipe_ingredients[real_name] = qty
            console.print(f"[green]Added {qty} {unit} of {real_name}[/green]")

    # Don't save a recipe that has no ingredients
    if not recipe_ingredients:
        console.print("[yellow]No ingredients added. Recipe creation cancelled.[/yellow]")
        return

    # Save the recipe under its dish name (re-using a name overwrites it)
    recipes[dish_name] = {
        "selling_price": selling_price,
        "ingredients": recipe_ingredients,
    }
    save_recipes(recipes)
    console.print(f"\n[bold green]✓ Successfully saved '{dish_name}' to recipe book![/bold green]")


# --- RECIPE DELETION ---
def delete_recipe():
    """Lets staff remove a recipe from the recipe book."""
    # Load the recipe book (an empty book if there are none)
    recipes = load_recipes() or {}

    if not recipes:
        console.print("[yellow]No recipes to delete.[/yellow]")
        return

    # Show a numbered list of saved recipes
    console.print("\n[bold cyan]Saved Recipes:[/bold cyan]")
    dish_list = list(recipes.keys())
    for idx, dish in enumerate(dish_list, start=1):
        console.print(f"{idx}. {dish}")

    # Pressing Enter or typing an invalid number cancels
    choice = Prompt.ask(
        "\nSelect recipe number to delete (or press Enter to cancel)",
        default="",
    ).strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(dish_list)):
        console.print("[yellow]Deletion cancelled.[/yellow]")
        return

    selected_dish = dish_list[int(choice) - 1]
    # Ask for confirmation before permanently deleting
    if not Confirm.ask(f"Permanently delete '{selected_dish}'?"):
        console.print("[yellow]Deletion cancelled.[/yellow]")
        return

    # Remove the recipe and save the updated recipe book
    del recipes[selected_dish]
    save_recipes(recipes)
    console.print(f"[bold green]✓ Deleted '{selected_dish}' from the recipe book.[/bold green]")


# --- DISH COSTING & MARGIN CALCULATOR ---
def calculate_dish_cost():
    """Calculates food cost per dish and profit margin using inventory unit prices."""
    df = load_inventory()
    recipes = load_recipes()

    # Costing needs the unit_price column from the inventory
    if df is None or "unit_price" not in df.columns:
        console.print("[red]Missing 'unit_price' column in inventory CSV.[/red]")
        return

    # Nothing to cost until at least one recipe exists
    if not recipes:
        console.print("[yellow]No recipes found. Add a recipe first![/yellow]")
        return

    # Let the user pick a dish by its number
    console.print("\n[bold cyan]Available Dishes:[/bold cyan]")
    dish_list = list(recipes.keys())
    for idx, dish in enumerate(dish_list, start=1):
        console.print(f"{idx}. {dish}")

    choice = Prompt.ask("\nSelect a dish number to view costing", choices=[str(i) for i in range(1, len(dish_list) + 1)])
    selected_dish = dish_list[int(choice) - 1]
    recipe_data = recipes[selected_dish]

    # Pull the selling price and ingredient list out of the recipe
    selling_price = recipe_data.get("selling_price", 0.0)
    ingredients_needed = recipe_data.get("ingredients", {})

    # Build a table showing each ingredient's cost while adding up the total
    total_cost = 0.0
    cost_table = Table(title=f"Recipe Cost Analysis: {selected_dish}")
    cost_table.add_column("Ingredient", style="bold white")
    cost_table.add_column("Qty Used", justify="right")
    cost_table.add_column("Unit Price", justify="right", style="dim")
    cost_table.add_column("Ingredient Cost", justify="right", style="green")

    # Look up each ingredient's unit price in the inventory (case-insensitive)
    for item, qty in ingredients_needed.items():
        match = df[df["ingredient"].str.lower() == item.lower()]
        if not match.empty:
            unit_price = float(match.iloc[0]["unit_price"])
            unit = str(match.iloc[0]["unit"])
            item_cost = unit_price * qty
            total_cost += item_cost
            cost_table.add_row(item, f"{qty} {unit}", f"${unit_price:.2f}", f"${item_cost:.2f}")
        # Ingredient isn't in the inventory: show N/A and count it as $0
        else:
            cost_table.add_row(item, f"{qty}", "N/A", "$0.00")

    console.print(cost_table)

    # Profit = selling price minus food cost; margin is a percentage of the selling price
    profit = selling_price - total_cost
    margin = (profit / selling_price * 100) if selling_price > 0 else 0.0

    # Print the summary (guarding against dividing by a $0 selling price)
    console.print(f"[bold]Selling Price:[/bold] ${selling_price:.2f}")
    console.print(f"[bold]Food Cost:[/bold] ${total_cost:.2f} ({(total_cost/selling_price*100) if selling_price else 0:.1f}% food cost ratio)")
    console.print(f"[bold green]Net Profit Margin per Dish:[/bold green] ${profit:.2f} ({margin:.1f}%)\n")


# --- SHIFT DEDUCTION / DEDUCT SALES ---
def deduct_dish_sales():
    """Deducts raw ingredient stock based on dishes sold during a shift."""
    df = load_inventory()
    recipes = load_recipes()

    # Need both an inventory and at least one recipe
    if df is None or not recipes:
        console.print("[yellow]No inventory or recipes found.[/yellow]")
        return

    # Choose which dish was sold
    console.print("\n[bold cyan]Select Dish Sold:[/bold cyan]")
    dish_list = list(recipes.keys())
    for idx, dish in enumerate(dish_list, start=1):
        console.print(f"{idx}. {dish}")

    choice = Prompt.ask("\nSelect dish number", choices=[str(i) for i in range(1, len(dish_list) + 1)])
    selected_dish = dish_list[int(choice) - 1]

    # How many were sold (must be a number greater than 0)
    sales_qty_str = Prompt.ask(f"How many orders of '{selected_dish}' were sold?")
    sales_qty = parse_amount(sales_qty_str, allow_zero=False)
    if sales_qty is None:
        console.print("[red]Invalid quantity entered (must be a number greater than 0).[/red]")
        return

    # For each ingredient: amount used = quantity per dish x number of dishes sold
    recipe_data = recipes[selected_dish]["ingredients"]
    deducted_summary = []

    for item, qty_per_dish in recipe_data.items():
        total_used = qty_per_dish * sales_qty
        # Find the ingredient in the inventory (case-insensitive)
        idx = df[df["ingredient"].str.lower() == item.lower()].index
        if not idx.empty:
            current_val = df.at[idx[0], "current_stock"]
            # Subtract the usage, but never let stock go below zero
            new_val = max(0.0, current_val - total_used)
            df.at[idx[0], "current_stock"] = new_val
            unit = df.at[idx[0], "unit"]
            deducted_summary.append(
                f"• {item}: -{total_used:.2f} {unit} (New balance: {new_val:.2f} {unit})"
            )
        # Ingredient isn't in the inventory: warn instead of failing
        else:
            deducted_summary.append(f"• [yellow]{item}: not found in inventory, skipped[/yellow]")

    # Save the updated stock levels back to the CSV
    df.to_csv(CSV_FILE, index=False)
    console.print(f"\n[bold green]✓ Deducted inventory for {sales_qty} x {selected_dish}:[/bold green]")
    # Print what was deducted for each ingredient
    for line in deducted_summary:
        console.print(line)


# --- STOCK TAKE ---
def interactive_stock_take():
    """Walks through every ingredient so staff can enter the current count."""
    df = load_inventory()
    if df is None:
        return

    console.print(Panel("[bold yellow]STARTING INTERACTIVE STOCK TAKE[/bold yellow]\nPress Enter to keep current stock value.", title="Inventory Take"))

    # Go through every ingredient; pressing Enter keeps the current value
    updated_count = 0
    for idx, row in df.iterrows():
        item_name = str(row["ingredient"])
        current_val = float(row["current_stock"])
        unit = str(row["unit"])

        user_input = Prompt.ask(
            f"Enter count for [bold white]{item_name}[/bold white] (in {unit})",
            default=str(current_val),
        ).strip()

        # Only accept numbers that are 0 or higher
        new_val = parse_amount(user_input)
        if new_val is None:
            console.print("[red]Invalid entry (must be a number, 0 or more); retaining current stock level.[/red]")
        elif new_val != current_val:
            df.at[idx, "current_stock"] = new_val
            updated_count += 1

    # Save all counts back to the CSV
    df.to_csv(CSV_FILE, index=False)
    console.print(f"\n[bold green]✓ Stock take complete! Updated {updated_count} item(s) in {CSV_FILE}.[/bold green]")


# --- LOW STOCK CHECK & REORDER LOG ---
def check_stock_and_log(csv_file=CSV_FILE, db_file=DB_FILE):
    """Lists items below their minimum level and optionally saves the reorder list to the database."""
    df = load_inventory()
    if df is None:
        return

    # Items whose current stock is below the minimum required
    low_stock = df[df["current_stock"] < df["min_required"]].copy()

    if low_stock.empty:
        console.print("[bold green]All stock levels are healthy! No items need reordering.[/bold green]")
        return

    # Order enough to get back up to the minimum, and timestamp this check
    low_stock["amount_to_order"] = low_stock["min_required"] - low_stock["current_stock"]
    low_stock["log_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Show the reorder list as a table
    table = Table(title="LOW STOCK & REORDER ACTION NEEDED!", title_style="bold red")
    table.add_column("Supplier", style="cyan", no_wrap=True)
    table.add_column("Ingredient", style="bold white")
    table.add_column("Current Stock", justify="right", style="yellow")
    table.add_column("Minimum Required", justify="right", style="dim")
    table.add_column("Order Quantity", justify="right", style="bold red")
    table.add_column("Unit", justify="left", style="green")

    # Sorted by supplier so each supplier's items appear together
    for _, row in low_stock.sort_values(by="supplier").iterrows():
        table.add_row(
            str(row["supplier"]),
            str(row["ingredient"]),
            f"{row['current_stock']:.1f}",
            f"{row['min_required']:.2f}",
            f"{row['amount_to_order']:.2f}",
            str(row["unit"]),
        )

    console.print(table)

    # Optionally save this list to the SQLite database as a history log
    if Confirm.ask("\nSave this reorder list to Database logs?"):
        try:
            with sqlite3.connect(db_file) as conn:
                low_stock.to_sql("reorder_log", conn, if_exists="append", index=False)
            console.print("[bold green]Saved reorder list to database logs![/bold green]")
        except Exception as e:
            console.print(f"[bold red]Failed to save to database:[/bold red] {e}")


# --- ORDER HISTORY ---
def view_order_history(db_file=DB_FILE):
    """Shows saved reorder logs by timestamp and lets the user inspect one."""
    # No database file means no reorder log has been saved yet
    if not os.path.exists(db_file):
        console.print("[yellow]Database not found![/yellow]")
        return

    # Get the distinct log timestamps, newest first
    with sqlite3.connect(db_file) as conn:
        try:
            dates_df = pd.read_sql_query("SELECT DISTINCT log_date FROM reorder_log ORDER BY log_date DESC", conn)
        except sqlite3.OperationalError:
            console.print("[yellow]No history recorded yet.[/yellow]")
            return

        if dates_df.empty:
            console.print("[yellow]No history recorded yet.[/yellow]")
            return

    # Turn the timestamps into a plain list for numbering
    dates = dates_df["log_date"].tolist()

    # Show the saved logs as a numbered table
    history_table = Table(title="Past Order Logs")
    history_table.add_column("#", style="dim", width=4)
    history_table.add_column("Log Timestamp", style="cyan")

    for idx, d in enumerate(dates, start=1):
        history_table.add_row(str(idx), str(d))

    console.print(history_table)

    # Pick a log to inspect, or press Enter to go back
    choice = Prompt.ask("Select log # to inspect (or press Enter to return)", default="")
    if not choice.isdigit() or not (1 <= int(choice) <= len(dates)):
        return

    selected_date = dates[int(choice) - 1]

    # Load every item saved in the chosen log
    with sqlite3.connect(db_file) as conn:
        detail_df = pd.read_sql_query("SELECT * FROM reorder_log WHERE log_date = ?", conn, params=(selected_date,))

    # Show the items in the selected log
    detail_table = Table(title=f"Log Detail: {selected_date}")
    detail_table.add_column("Ingredient", style="bold white")
    detail_table.add_column("Order Amount", style="bold green")
    detail_table.add_column("Supplier", style="cyan")

    for _, row in detail_df.iterrows():
        detail_table.add_row(
            str(row["ingredient"]),
            f"{row['amount_to_order']} {row['unit']}",
            str(row["supplier"]),
        )

    console.print(detail_table)


# --- SUPPLIER PURCHASE ORDERS ---
def generate_supplier_orders():
    """Creates a ready-to-send purchase order message for each supplier with low-stock items."""
    df = load_inventory()
    if df is None:
        return

    # Items below their minimum level need to be reordered
    low_stock = df[df["current_stock"] < df["min_required"]].copy()
    if low_stock.empty:
        console.print("[bold green]All stock levels are healthy! No orders needed.[/bold green]")
        return

    low_stock["amount_to_order"] = low_stock["min_required"] - low_stock["current_stock"]
    # One purchase order is written per supplier
    suppliers = low_stock["supplier"].unique()

    console.print(Panel("[bold yellow]GENERATED SUPPLIER PURCHASE ORDERS[/bold yellow]", title="Purchase Orders"))

    for supplier in suppliers:
        # Only the items that come from this supplier
        items = low_stock[low_stock["supplier"] == supplier]
        # Build the text of the order message
        order_text = f"SUBJECT: Purchase Order - {datetime.now().strftime('%Y-%m-%d')}\n"
        order_text += f"TO: {supplier} Sales Team\n\n"
        order_text += "Please fulfill the following reorder for our kitchen:\n"

        for _, row in items.iterrows():
            order_text += f" • {row['ingredient']}: {row['amount_to_order']:.2f} {row['unit']}\n"

        order_text += "\nPlease confirm delivery schedule and total price.\nThank you,\nKitchen Manager"

        # Print the order so it can be copied into an email
        print(f"[bold cyan]=== {supplier.upper()} ===[/bold cyan]")
        print(order_text)
        print("-" * 50)


# --- INVENTORY SEARCH ---
def search_inventory():
    """Finds ingredients whose name contains the text the user types."""
    df = load_inventory()
    if df is None:
        return

    # Case-insensitive, plain-text search (regex=False so characters like ( or + are safe)
    term = Prompt.ask("Enter ingredient name to search").strip().lower()
    matches = df[df["ingredient"].str.lower().str.contains(term, regex=False)]

    if matches.empty:
        console.print("[yellow]No matching item found![/yellow]")
        return

    table = Table(title=f"Search results for '{term}'")
    table.add_column("Ingredient", style="bold white")
    table.add_column("Current Stock", justify="right")
    table.add_column("Minimum Required", justify="right")
    table.add_column("Unit")
    table.add_column("Supplier", style="cyan")

    for _, row in matches.iterrows():
        # Show current stock in red when it is below the minimum, green otherwise
        status_color = "red" if row["current_stock"] < row["min_required"] else "green"
        table.add_row(
            str(row["ingredient"]),
            f"[{status_color}]{row['current_stock']}[/{status_color}]",
            str(row["min_required"]),
            str(row["unit"]),
            str(row["supplier"]),
        )

    console.print(table)


# --- MAIN MENU ---
def main():
    """Shows the menu in a loop and runs the chosen option until the user exits."""
    # Redisplay the menu after every action until Exit is chosen
    while True:
        console.print("\n[bold blue]=== RESTAURANT INVENTORY MANAGEMENT ===[/bold blue]")
        console.print("\n1. [bold yellow]Interactive Stock Take (Update Counts)[/bold yellow]")
        console.print("2. [bold magenta]Check Low Stock & Create Reorder Log[/bold magenta]")
        console.print("3. [cyan]View Order History[/cyan]")
        console.print("4. [bold green]Recipe Costing & Profit Calculator[/bold green]")
        console.print("5. [bold blue]Add New Menu Recipe[/bold blue]")
        console.print("6. [bold red]Deduct Sold Dishes from Stock[/bold red]")
        console.print("7. [bold cyan]Generate Supplier Email Purchase Orders[/bold cyan]")
        console.print("8. [white]Search Current Inventory[/white]")
        console.print("9. [bold red]Delete a Menu Recipe[/bold red]")
        console.print("\n10. [dim white]Exit[/dim white]")

        # Only options 1 to 10 are accepted
        choice = Prompt.ask("\nSelect an option!", choices=[str(i) for i in range(1, 11)])

        # Run the function for the chosen menu option
        if choice == "1":
            interactive_stock_take()
        elif choice == "2":
            check_stock_and_log()
        elif choice == "3":
            view_order_history()
        elif choice == "4":
            calculate_dish_cost()
        elif choice == "5":
            add_custom_recipe()
        elif choice == "6":
            deduct_dish_sales()
        elif choice == "7":
            generate_supplier_orders()
        elif choice == "8":
            search_inventory()
        elif choice == "9":
            delete_recipe()
        elif choice == "10":
            console.print("[italic gray]Closing Software...[/italic gray]")
            break


# Start the app only when this file is run directly (not when imported)
if __name__ == "__main__":
    main()