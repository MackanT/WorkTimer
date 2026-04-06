
# DevOps contacts

`config/devops_contacts.yml` stores per-customer contacts and assignees used when creating DevOps work items. All management is done through the **Settings** page inside WorkTimer.

#### Data shape

Each customer entry contains:

- `contacts`: delivery contact names (strings)
- `assignees`: assignee email addresses that have access to the devops solution (strings)
- `default_assignee` (optional): pre-selected assignee — must be one of the values in `assignees`

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
    default_assignee: "ops@customerb.com"
```

#### Managing contacts

Navigate to **Settings → DevOps Contacts** in the left sidebar.

##### Adding a customer

Click the **+** button next to *DevOps Contacts* in the sidebar. Enter the customer name and press Add. The customer appears immediately in the sidebar sub-list.

##### Editing a customer

Click the customer name in the sidebar. The right panel shows three sections:

- **Contacts** — type a name and press the add button; click ✕ on a chip to remove
- **Assignees** — type an email and press the add button; click ✕ to remove
- **Default Assignee** — pick from the assignees dropdown and press save

Changes take effect immediately (no restart needed).

##### Removing a customer

Select the customer, then press the delete (🗑) button at the top of the detail panel.

##### Resetting to defaults

Click the **↺** button next to *DevOps Contacts* in the sidebar to restore `config/devops_contacts.yml` from the bundled template.

#### DevOps sync

The sync strip at the bottom of the Contacts panel controls data synchronisation with Azure DevOps:

- **Incremental** — fetches changes since the last sync
- **Full Sync** — re-downloads all epics, features, and stories

Last sync times are shown next to each button.

#### Troubleshooting

**Q: A customer is missing from the contacts panel**

- The customer must be added manually via Settings → DevOps Contacts (+ button).
- Customer names do not need to match the database — they are free-form.

**Q: Assignee dropdown is empty when creating a work item**

- Open Settings → DevOps Contacts, select the customer, and add at least one email under Assignees.

**Q: Changes don't appear after editing**

- Changes made in Settings are saved instantly. If you edited the YAML file directly, restart the application.

