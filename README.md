A lightweight, terminal-based inventory manager for restaurants and kitchens. Track ingredient stock, get low-stock alerts, generate supplier purchase orders, build a recipe book, calculate dish costs and profit margins, and automatically deduct ingredients when dishes are sold.

Everything runs locally and stores data in plain files (a CSV, a JSON file, and a SQLite database), so there is no server, account, or internet connection required.

How to Run:

Download and Launch the executable:
Wait a second, as it needs time for the program to load
Select the option you want, listed by numbers below (See 'Visual Demo' below for information)

How to Upload Personal Inventory:

Create an excel, and create six columns and name them in order: 

[ingredient, current_stock, min_required, unit, unit_price, supplier]

Fill in the information below each column.

IMPORTANT!: When done, download the file as a .csv, and name it 'Inventory.csv'
Go to the folder where the executable is
Paste the file into the folder with the executable, and run!

Features:

Interactive stock take: walk through every ingredient and update counts. Press Enter to keep the current value.
Low-stock check and reorder log: lists everything below its minimum level, grouped by supplier, with the quantity needed to get back to the minimum. Reorder lists can be saved to a database log.
Order history: browse past reorder logs by timestamp.
Recipe costing and profit calculator: shows ingredient costs, food cost percentage, and profit margin per dish using the unit prices in your inventory.
Recipe book: add menu items with a selling price and the ingredients each dish uses.
Sales deduction: enter how many of a dish were sold and the app subtracts the matching ingredients from stock.
Supplier purchase orders: generates a ready-to-send order message for each supplier with items to reorder.
Inventory search: find ingredients by name, with low-stock items highlighted.
Recipe deletion: remove recipes you no longer need, with confirmation.

Tech Stack:

Language: Python
Data Management: pandas & SQLite3
Terminal UI: Rich (color-coded tables, panels, prompts, and console styling)

Visual Demo:

=== RESTAURANT INVENTORY MANAGEMENT ===

Interactive Stock Take (Update Counts)

Check Low Stock & Create Reorder Log

View Order History

Recipe Costing & Profit Calculator

Add New Menu Recipe

Deduct Sold Dishes from Stock

Generate Supplier Email Purchase Orders

Search Current Inventory

Delete a Menu Recipe

Exit

Select an option! [1/2/3/4/5/6/7/8/9/10]:

Prerequisites to Run from Source:

Python 3.9 or newer (developed and tested on Python 3.12)
pandas
rich
License: Distributed under the MIT License. See LICENSE for more information.
