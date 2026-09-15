# Tracker contacts

`config/devops_contacts.yml` stores per-customer **contacts** and **assignees** used in the work-item forms (both Azure DevOps and Jira). All management is done from **Settings → Trackers → Contacts** inside WorkTimer — you never need to edit the file by hand.

#### Data shape

Each customer entry contains:

- `contacts`: delivery contact names (free-form strings, offered in the *Contact person* field)
- `assignees`: people the tracker can assign work to — display names or emails, whatever your tracker accepts
- `default_assignee` (optional): pre-selected assignee — must be one of the values in `assignees`

```yaml
customers:
  "Customer A":
    contacts:
      - "John Doe"
      - "Jane Smith"
    assignees:
      - "dev1@company.com"
      - "Dev Two"
    default_assignee: "dev1@company.com"

  "Customer B":
    contacts:
      - "Anne Example"
    assignees:
      - "ops@customerb.com"
    default_assignee: "ops@customerb.com"
```

#### Managing contacts

Open **Settings → Trackers** and scroll to the **Contacts** card. Pick a customer in the dropdown; the detail below shows three sections:

- **Contacts** — type a name and press the add button; click ✕ on a chip to remove
- **Assignees** — type a value and press the add button, **or press the cloud button** to fetch the project's members straight from the tracker and tick the ones to import
- **Default Assignee** — pick from the assignees dropdown and save

Changes take effect immediately (no restart needed).

- **Add customer** — button next to the dropdown; the name is free-form and does not need to match the database
- **Delete customer** — the 🗑 button at the top of the detail section
- **Reset to defaults** — the ↺ button next to the dropdown restores the file from the bundled template

#### Troubleshooting

**Q: A customer is missing from the contacts panel**

- Customers are added here manually (Add customer button) — the list is independent of the database.

**Q: Assignee dropdown is empty when creating a work item**

- Select the customer under Settings → Trackers → Contacts and add at least one assignee — the cloud button imports them from the tracker in one go.

**Q: Changes don't appear after editing**

- Changes made in Settings are saved instantly. If you edited the YAML file directly, restart the application.
