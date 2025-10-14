# 🚀 WorkTimer User Guide

Welcome to **WorkTimer** – your all-in-one time tracking and DevOps management tool! This guide will help you get started and make the most of the app’s features.


## 📋 How to Use WorkTimer

Follow these steps to get started with tracking your work:

1. **Add Customer(s)**
  - Go to the **Data Input** tab.
  - Fill in the customer details and click 'Add'.

2. **Add Project(s)**
  - In the **Data Input** tab, select the project section.
  - Enter project details and link them to a customer, then click 'Add'.

3. **Add Bonus(es)**
  - Still in the **Data Input** tab, switch to the bonus section.
  - Enter bonus information and save.

4. **Start and Stop Times for Customers**
  - Use the **Time Tracking** tab to start and stop timers for your customers and projects.
  - Select the customer and project, then use the checkbox or timer controls to log your work.

All your entries will be saved and visible in the app for review and reporting.

---

## 🏁 Getting Started

1. **Launch the App**
   - Start WorkTimer by running the Python script:
     ```
     python [main.py]
     ```
     or by running (Docker installation, see bottom of guide)
     ```
     docker compose up
     ```
   - Open your browser and navigate to `http://localhost:8080`.

---

## ⏰ Time Tracking

The time tracking view lets you filter and display your work entries based on selected time span, custom date ranges, and whether you want to see tracked hours or bonus amounts. Adjust these options to focus on the period and data most relevant to you.

---

## 📝 Data Input


The Data Input tab is your central place to create, edit, enable, or disable customers and projects. The simplified UI lets you make all changes without writing SQL queries—just use the forms and options provided.

---

## 🛠️ DevOps Settings


The DevOps Settings tab currently supports creating user stories linked to your projects. More features, such as epic and feature management, will be added in future updates.

---

## 🗃️ Query Editors


In the Query Editors tab, you can run either premade queries by selecting them from a list and pressing F5, or write your own custom SQL to find the values you need. Save and edit your favorite queries as custom queries for quick access.

For simple modifications to the default tables, just click on a row in the query output—this will open a popup where you can make changes directly.

---

## 📊 Log & Info


The Application Log records most actions performed in the program, giving you a real-time overview of activity. Note that logs are not saved anywhere—if you restart the server, the log history will be cleared.

The Info tab provides documentation, usage tips, and troubleshooting help to guide you through the app.

---

## 🧑‍💻 Troubleshooting

If you encounter any issues, check the Log tab for error messages. For further help, contact Marcus Toftås.

---


## 🐳 Running with Docker

You can run WorkTimer using Docker for 24/7 access:

1. **Install Docker**
  - Download and install Docker Desktop from [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)

2. **Get the Project Files**
  - Make sure you have the `Dockerfile`, `docker-compose.yml`, and any required config files.

3. **Start the App**
  - Open a terminal in the project directory and run:
    ```sh
    docker compose up
    ```
  - This will build and start all services defined in your compose file.

4. **Access the App**
  - Open your browser and go to `http://localhost:8080`

No need to install Python or dependencies locally—the container handles everything!

---