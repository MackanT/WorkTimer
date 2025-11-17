
# DevOps contacts

This file documents the data shape used by WorkTimer for DevOps contacts and how to (safely) update it.

#### Summary

`config/devops_contacts.yml` is a YAML mapping of customers. Each customer entry contains:

- `contacts`: a list of contact person names (strings) — the delivery contacts for the customer
- `assignees`: a list of assignee email addresses (strings) — emails that can be assigned DevOps tasks
- `default_assignee` (optional): the default assignee email (string) — must be one of the values in `assignees`

Example `config/devops_contacts.yml` snippet

```yaml
customers:
  "Customer A":
    contacts:
      - "John Doe"
      - "Jane Smith"
    assignees:
      - "dev1@company.com"
      - "dev2@company.com"
    default_assignee: "dev1@company.com"

  "Customer B":
    contacts:
      - "Anne Example"
    assignees:
      - "ops@customerb.com"
    # default_assignee omitted when not needed
```

#### How to generate the file

The generator (`scripts/generate_devops_contacts.py`) creates placeholder entries for each customer found in the database. It can create the `config/` folder if it does not exist.

Run the generator from the project root:

```powershell
python .\scripts\generate_devops_contacts.py
```

After running, edit `config/devops_contacts.yml` and replace placeholder comments with real names and emails.

###### Command-line flags

The generator supports the following options:

- `--preview` — run the generation and print the result instead of saving
- `--db_name <file>` — database file to read (default: `data_dpg.db`)
- `--location <file>` — output filename relative to `--folder` (default: `config/devops_contacts.yml`)

Use these flags for testing; the defaults are suitable for normal usage.

##### Adding a new customer

Option 1 — Automatic:

```powershell
python .\scripts\generate_devops_contacts.py
```

Option 2 — Manual: edit `config/devops_contacts.yml` and add:

```yaml
customers:
  "New Customer Name":
    contacts:
      - "Contact Name 1"
      - "Contact Name 2"
    assignees:
      - "email@company.com"
    default_assignee: "email@company.com"
```

##### Updating an existing customer

1. Edit `config/devops_contacts.yml` and add/remove values.
2. Run the validator to ensure the file is valid.
3. Restart the application to pick up the changes.

#### Validation

A validator is available at `scripts/validate_devops_contacts.py`. It checks:

- that `customers` exists
- that each customer has `contacts` (list) and `assignees` (list)
- that `default_assignee` (if present) is a string and appears in `assignees`

Run the validator:

```powershell
python .\scripts\validate_devops_contacts.py
# or validate a specific file:
python .\scripts\validate_devops_contacts.py --location .\config\devops_contacts.yml
```

#### After updating

- Restart the WorkTimer service or the NiceGUI app for changes to take effect (the UI is configuration-driven and reads the file on startup).
- Verify in the UI that the customer contact appears correctly in the DevOps form/dropdown.


#### Troubleshooting

**Q: Dropdowns are empty**

- Check that `config/devops_contacts.yml` exists.
- Run the generator: `python .\scripts\generate_devops_contacts.py`.
- Check the application logs/console for warnings on startup.

**Q: Changes don't appear**

- Restart the application after editing the YAML.
- Run the validator and fix any reported errors.

**Q: A new customer doesn't show options**

- Run the generator script to add the customer, or add the customer manually to `devops_contacts.yml`.
- Ensure the customer name exactly matches the customer entry in the database.

