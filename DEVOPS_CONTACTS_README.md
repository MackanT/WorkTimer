# DevOps Contacts Configuration Guide

## Overview
This system allows you to maintain customer-specific contact persons and assignees for DevOps user stories, without storing sensitive contact information in version control.

## Quick Start

### 1. Generate the Config File
Run the auto-generator script to create `devops_contacts.yml` from your database:

```bash
python generate_devops_contacts.py
```

This will:
- Read all active customers from your database
- Create/update `config/devops_contacts.yml` with customer entries
- Preserve any existing contact data if the file already exists

### 2. Edit the Config File
Open `config/devops_contacts.yml` and replace the placeholder comments with actual data:

```yaml
customers:
  "Acme Corporation":
    contacts:
      - "John Doe"
      - "Jane Smith"
      - "Bob Johnson"
    assignees:
      - "alice@yourcompany.com"
      - "bob@yourcompany.com"
      - "charlie@yourcompany.com"
  
  "Tech Startup Inc":
    contacts:
      - "Sarah Connor"
      - "Mike Wilson"
    assignees:
      - "dev1@yourcompany.com"
      - "dev2@yourcompany.com"

default:
  contacts: []
  assignees:
    - "unassigned"
```

### 3. Add to .gitignore
**IMPORTANT:** Add this line to your `.gitignore` file:

```
config/devops_contacts.yml
```

This keeps sensitive contact information out of version control.

## How It Works

### In the UI
When creating a DevOps User Story:

1. **Select Customer** - Choose a customer from the dropdown
2. **Contact Person** - Dropdown auto-populates with customer-specific contacts
   - You can also type a new contact name (not in the list)
3. **Assigned To** - Dropdown auto-populates with customer-specific assignees
   - You can also type a new assignee email (not in the list)

### Dynamic Updates
- When you select a different customer, the Contact and Assignee dropdowns update automatically
- The system uses the `parent: customer_name` relationship in the YAML config
- If a customer isn't found in `devops_contacts.yml`, default options are used

## File Structure

```
config/
  ├── devops_contacts.yml.template  # Template/example file (in git)
  ├── devops_contacts.yml          # Your actual data (NOT in git)
  └── config_devops_ui.yml          # UI configuration
```

## Maintenance

### Adding a New Customer
Option 1 - Automatic:
```bash
python generate_devops_contacts.py
```

Option 2 - Manual:
Edit `config/devops_contacts.yml` and add:
```yaml
customers:
  "New Customer Name":
    contacts:
      - "Contact Name"
    assignees:
      - "email@company.com"
```

### Updating Contacts
Simply edit `config/devops_contacts.yml` - changes take effect on next app restart.

### Sharing with Team
1. Each team member runs `generate_devops_contacts.py`
2. Each team member customizes their own `devops_contacts.yml`
3. The template file is shared via git for reference

## Technical Details

### Config Structure
```yaml
customers:
  "<CustomerName>":
    contacts: [list of contact person names]
    assignees: [list of assignee emails]

default:
  contacts: [fallback contacts if customer not found]
  assignees: [fallback assignees if customer not found]
```

### Field Configuration (in config_devops_ui.yml)
```yaml
- name: contact_person
  type: select
  with_input: true          # Allows custom input
  options_source: contact_persons  # Links to prep_devops_data
  parent: customer_name     # Updates when customer changes

- name: assigned_to
  type: select
  with_input: true
  options_source: assignees
  parent: customer_name
```

### Data Flow
1. `setup_config()` loads `devops_contacts.yml`
2. `prep_devops_data()` creates customer-specific dictionaries
3. `assign_dynamic_options()` assigns options to fields
4. `bind_parent_relations()` creates update handlers
5. When customer changes, options auto-update via parent relationship

## Best Practices

✅ **DO:**
- Keep `devops_contacts.yml` in `.gitignore`
- Run the generator script when customers change
- Use the template as a reference
- Document your contact data structure

❌ **DON'T:**
- Commit `devops_contacts.yml` to version control
- Store passwords or sensitive tokens in this file
- Hard-code contacts in the application code

## Troubleshooting

**Q: Dropdowns are empty**
- Check if `config/devops_contacts.yml` exists
- Run `python generate_devops_contacts.py`
- Check console for warnings on startup

**Q: Changes don't appear**
- Restart the application after editing the YAML
- Check YAML syntax (use a YAML validator)

**Q: New customer doesn't show options**
- Run the generator script to add the customer
- Or manually add the customer to `devops_contacts.yml`
- Make sure customer name exactly matches database

**Q: Want to share default options with team**
- Update `devops_contacts.yml.template` with examples
- Commit the template (not the actual `devops_contacts.yml`)
- Team members copy template and customize
