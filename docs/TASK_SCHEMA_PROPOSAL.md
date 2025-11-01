# Task Management Schema Proposal

## Current State Analysis

**YAML Fields (config_tasks.yml):**
- title, description, status, priority, assigned_to, customer_name, project_name, due_date, estimated_hours, tags

**Missing Database Table:**
- No Tasks table exists in database.py
- Code references `SELECT * FROM Tasks` but table doesn't exist

## Recommended Database Schema

### Core Task Table
```sql
CREATE TABLE tasks (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    
    -- Status & Priority
    status TEXT NOT NULL DEFAULT 'To Do', 
    -- Values: 'To Do', 'In Progress', 'In Review', 'Done', 'Blocked'
    priority TEXT NOT NULL DEFAULT 'Medium',
    -- Values: 'Low', 'Medium', 'High', 'Critical'
    
    -- Assignment & Organization
    assigned_to TEXT,
    customer_id INTEGER,
    project_id INTEGER,
    parent_task_id INTEGER, -- For subtasks
    
    -- Time Management
    due_date DATE,
    estimated_hours REAL DEFAULT 0,
    actual_hours REAL DEFAULT 0,
    progress_percentage INTEGER DEFAULT 0, -- 0-100
    
    -- Metadata
    tags TEXT, -- JSON array or comma-separated
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    created_by TEXT,
    updated_by TEXT,
    
    -- Foreign Keys
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (parent_task_id) REFERENCES tasks(task_id)
);
```

## Field Justification

### Essential Fields (Must Have)
- **task_id**: Primary key for unique identification
- **title**: Core task description
- **status**: Current state tracking
- **priority**: Importance ranking
- **created_at/updated_at**: Audit trail
- **customer_id/project_id**: Links to existing project structure

### Important Fields (Should Have)
- **due_date**: Deadline management
- **estimated_hours**: Planning and workload estimation
- **assigned_to**: Responsibility assignment
- **description**: Detailed task information

### Nice-to-Have Fields (Could Have)
- **parent_task_id**: Enables task hierarchies/subtasks
- **actual_hours**: Time tracking integration
- **progress_percentage**: Visual progress indicators
- **completed_at**: Completion tracking
- **tags**: Flexible categorization
- **created_by/updated_by**: User attribution

### Optional Advanced Fields (Won't Have for Now)
- **external_reference**: Links to external systems (GitHub issues, etc.)
- **attachments**: File references
- **comments**: Task discussion threads
- **watchers**: Notification recipients
- **custom_fields**: Flexible metadata

## Integration Considerations

### With Existing Time Tracking
- Tasks could reference time entries
- `actual_hours` could auto-calculate from time table
- Time entries could optionally link to specific tasks

### With Customer/Project Structure
- Uses existing customer_id and project_id foreign keys
- Maintains current organizational hierarchy
- Enables customer-filtered task views

### With User Management
- `assigned_to` field can reference existing user system
- `created_by`/`updated_by` for audit trail

## Recommended Implementation Order

1. **Phase 1 - Core Functionality**
   - Create basic tasks table with essential fields
   - Implement CRUD operations (insert_task, update_task, delete_task)
   - Basic UI with title, description, status, priority

2. **Phase 2 - Integration**
   - Add customer/project relationships
   - Connect to existing time tracking
   - Assignment and due date features

3. **Phase 3 - Advanced Features**
   - Progress tracking and reporting
   - Task hierarchies (parent/child)
   - Tags and advanced filtering
   - Time integration and auto-calculation

## YAML Updates Needed

- Remove database-incompatible fields
- Add timestamp handling
- Ensure field names match database columns
- Add proper foreign key relationships for customer/project dropdowns