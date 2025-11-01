# Task Visual Customization

This document explains how to customize the visual appearance (icons and colors) of customers and projects in the task management system.

## Quick Start

1. **Generate the configuration file:**
   ```bash
   python scripts/generate_task_visuals.py
   ```

2. **Customize the generated file:**
   Edit `config/task_visuals.yml` with your preferred icons and colors

3. **Restart the application** to see the changes

## Configuration Structure

The `task_visuals.yml` file has this structure:

```yaml
visual:
  customers:
    "Customer Name":
      icon: "business"
      color: "blue"
    default:
      icon: "group"
      color: "blue-grey"
  
  projects:
    "Project Name":
      icon: "code"
      color: "purple"
    default:
      icon: "folder"
      color: "indigo"
```

## Available Icons

Use Material Design icon names (without the `md-` prefix):

### Customer Icons
- `business` - Generic business
- `apartment` - Apartment/residential
- `store` - Retail store
- `factory` - Industrial/manufacturing
- `account_balance` - Bank/financial
- `domain` - Corporate domain
- `corporate_fare` - Corporate building

### Project Icons
- `code` - Software development
- `web` - Web project
- `mobile_friendly` - Mobile app
- `cloud` - Cloud/SaaS
- `storage` - Data storage
- `analytics` - Analytics/reporting
- `build` - Build/DevOps
- `settings` - Configuration/tools

### Generic Icons
- `group` - People/team
- `folder` - Generic folder
- `work` - Work/business
- `schedule` - Time/scheduling

## Available Colors

Use Quasar color names:

### Primary Colors
- `red`, `pink`, `purple`, `deep-purple`
- `indigo`, `blue`, `light-blue`, `cyan`
- `teal`, `green`, `light-green`, `lime`
- `yellow`, `amber`, `orange`, `deep-orange`
- `brown`, `grey`, `blue-grey`

### Usage Tips
- Use **darker colors** for better contrast
- **Group related customers/projects** with similar color families
- Use **distinctive icons** to make scanning easier

## Automation

The generation script automatically:
1. Scans your database for existing customers and projects
2. Assigns suggested icons and colors
3. Preserves any existing customizations

## Git Integration

The `task_visuals.yml` file should be in `.gitignore` to keep personal customizations private, just like `devops_contacts.yml`.

## Examples

```yaml
visual:
  customers:
    "Rowico Home":
      icon: "chair"
      color: "brown"
    "Microsoft":
      icon: "computer" 
      color: "blue"
    "Startup Inc":
      icon: "rocket_launch"
      color: "orange"
      
  projects:
    "Data Analytics":
      icon: "analytics"
      color: "light-blue"
    "Mobile App":
      icon: "mobile_friendly"
      color: "green"
    "API Backend":
      icon: "api"
      color: "purple"
```