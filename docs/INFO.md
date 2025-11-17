# 🚀 WorkTimer User Guide (WIP)

Welcome to **WorkTimer** – your modern time tracking and DevOps management solution! This guide covers everything you need to know to track time, manage tasks, and integrate with Azure DevOps.

---

## 🏁 Getting Started

### Launching the Application

**Option 1: Direct Python Execution**
```bash
uv run -m src.main
```

**Option 2: Docker (Recommended for 24/7 Operation)**
```bash
docker compose up
```

Once started, open your browser to **`http://localhost:8080`**

### Initial Setup

1. **Add Your First Customer**
   - Navigate to **Data Input** → **Customer** tab
   - Fill in customer name and (optionally) Azure DevOps details
   - Click **Add**

2. **Create Projects**
   - Navigate to **Data Input** → **Project** tab
   - Select your customer from the dropdown
   - Enter project details and click **Add**

3. **Configure Bonuses** (Optional)
   - Navigate to **Data Input** → **Bonus** tab
   - Add bonus entries as a percentage (e.g., 25 for 25%) and the start date
   - If no bonus is configured, all calculations default to 0% bonus

You're now ready to start tracking time!

---

## ⏰ Time Tracking

Track your billable hours with an intuitive customer/project interface.

### Features
- **Time Span Selection** - View data by Day, Week, Month, Year, All-Time, or Custom range
- **Display Toggle** - Switch between tracked time and bonus amounts
- **Live Timers** - Start/stop timers with a single checkbox click
- **Visual Indicators** - Active timers shown with animated icons in tab header

### Workflow
1. Select your desired time span (default: Day)
2. Find the customer and project you're working on
3. Click the checkbox to start tracking time
4. Click again to stop and log the entry

**Pro Tip:** When you stop a timer, you'll have the option to attach a comment or link to a DevOps work item.

---

## ✅ To-Do System

Manage tasks independently from DevOps with the built-in task system.

### Features
- **Card & Table Views** - Toggle between visual cards and detailed table layouts
- **Rich Task Data** - Track titles, descriptions, due dates, priority, status, customer, and project
- **Smart Filtering** - Sort by due date, priority, status, or customer/project
- **Quick Actions** - Click cards to view details, edit tasks, or mark as complete

### Creating Tasks
1. Go to **To-Do** tab
2. Click the **+** button or switch to **Add** tab
3. Fill in task details (title is required)
4. Click **Add Task**

### Managing Tasks
- **Edit**: Click any task card, then switch to **Update** tab
- **Complete**: Click the checkbox on any task
- **View Details**: Click a card to see full description and metadata

---

## 📝 Data Input

Central hub for managing all your entities (customers, projects, bonuses, DevOps work items).

### Customers
- **Add**: Create new customers with optional DevOps PAT tokens
- **Update**: Modify customer details (changes propagate to projects)
- **Disable/Reenable**: Soft-delete customers without losing historical data

### Projects
- **Add**: Link projects to customers with descriptive names
- **Update**: Change project details or update devpos default ids
- **Disable/Reenable**: Archive projects while preserving time entries

### Bonuses
- **Add**: Record flexible bonus percent

### DevOps Work Items
- **User Stories**: Create stories with markdown descriptions and live preview
- **Features**: Create features with parent epic linking
- **Epics**: Create top-level epics for organizing work
- **Parent Linking**: Automatically link child items to parent features/epics

**Note:** DevOps integration requires valid PAT token and organization URL configured per customer.

---

## 🔍 Query Editors

Powerful SQL interface for custom data analysis and table editing.

### Features
- **Preset Queries** - Click built-in queries for common reports
- **Custom Queries** - Write, save, and manage your own SQL queries
- **Syntax Validation** - Real-time SQL syntax checking before execution
- **Result Editing** - Click any row in results to edit values directly
- **Keyboard Shortcuts** - Press **F5** to execute queries

### Workflow
1. Select a preset query or write custom SQL in the editor
2. Press **F5** or click **Execute**
3. View results in the table below
4. Click any row to edit values (opens edit dialog)

### Managing Custom Queries
- **Save**: Click **Save As** to store your SQL for reuse
- **Update**: Modify and save changes to existing custom queries
- **Delete**: Remove custom queries you no longer need

**Pro Tip:** Use the color-coded editor to spot syntax errors before execution.

---

## 🗃️ Database Tools

Advanced features for database management and migration.

### Schema Comparison
- Compare your current database schema with older versions
- Identify structural changes and plan migrations
- Generate sync SQL for schema updates

### Database Script Runner
- Execute SQL scripts on any database file
- Save query results for analysis or migration
- Useful for migrating data between database versions

**Note:** These tools are for users who participated in the alpha builds of the program and or in the future want to migrate to a newer incompatible version

---

## 📊 Log & Info

### Application Log
- **Real-time Monitoring** - See all actions as they happen
- **Color-Coded Messages** - Info (white), warnings (yellow), errors (red)
- **Source Tracking** - Identify which engine generated each log entry
- **Modern Interface** - Dark theme with monospace font for readability

**Important:** Logs are stored in memory only and reset on application restart.

### Info Tab
Access this guide and additional documentation directly within the application.

---

## 🧑‍💻 Troubleshooting

### Common Issues

**Application won't start**
- Check that port 8080 is not in use by another application
- Verify Python 3.11+ is installed (`python --version`)

**DevOps integration not working**
- Verify PAT token has correct permissions (Work Items: Read, Write, Manage)
- Check that organization URL is correct (should be just the org name, not full URL)
- Review Application Log for specific error messages

**Database errors**
- Ensure `worktimer.db` file exists and is not locked by another process
- Check that you have write permissions in the application directory
- Review Application Log for SQL error details

**UI not responsive**
- Hard refresh your browser (Ctrl+F5 or Cmd+Shift+R)
- Clear browser cache
- Check Application Log for JavaScript errors

### Getting Help
For additional support, contact **Marcus Toftås** or check the GitHub repository issues.

---

## 🐳 Docker Deployment

Run WorkTimer in a container for 24/7 availability without local Python installation.

### Prerequisites
- Docker Desktop installed ([download here](https://www.docker.com/products/docker-desktop))
- `docker-compose.yml` and `Dockerfile` in project root

### Deployment Steps

1. **Build and Start**
   ```bash
   docker compose up
   ```
   Add `-d` flag for detached mode (runs in background)

2. **Access the Application**
   Open browser to `http://localhost:8080`

3. **View Logs**
   ```bash
   docker compose logs -f
   ```

4. **Stop the Application**
   ```bash
   docker compose down
   ```

### Data Persistence
The database file is mounted as a volume, so your data persists across container restarts. Ensure the volume mapping in `docker-compose.yml` points to your desired data location.

---

## 💡 Tips & Best Practices

- **Daily Routine**: Start each day by reviewing your To-Do list and setting task priorities
- **Time Tracking**: Start timers at the beginning of work sessions, not retroactively
- **Comments**: Add meaningful comments when stopping timers to improve DevOps integration
- **Custom Queries**: Save frequently-used SQL queries for quick access
- **DevOps Sync**: Let automatic sync run—full refresh happens daily at 2 AM, incremental hourly
- **Backup**: Regularly backup your `worktimer.db` file before major operations

---
