### TODO

- Easy way to add time in post. For ex. change customer/project/git
(auto-set date at midnight)~
- update customer/project should also update times values!
- Devops connector
- Make PAT-tokens etc masked
- Option to reenable existing customer/project

- Add custom quick selections


### Buggar

- Varning om att Bonus måste skapas upp, annars krash
- comment not wraping text -- Not possible yet 2025-06-26: https://github.com/hoffstadt/DearPyGui/issues/1504



### Completed
- ~when minimizing and opening window all customer projects are minimized~
- ~customer tab to tall, moving log to bottom~
- ~Amount shows incorrect wage. I.e project_name = Förvaltning date_key = 20250502 is 133.31, shows 99.99~
- ~_get_value_from_db returns wrongful datatypes~
- ~pre_log should not populate "created table" if it did not run. And only run generate_dates if necessary~
- ~Fix so git-id is displayed as int~
- ~.JSON fil auto-populeras inte med nya customer_id~ Not applicable after move to sql-table
- ~Efter remove customer döljs den inte från "knapparna"~

- ~End of period groupings~
- ~project_name + customer_name in time is updated automatically based on id~
- ~Color indicator or other to show customers with active projects~
- ~Started timer cannot be removed without sql~
- ~Post to devops is default-filled based on if value exists or not~
- ~change json sort file to be a column in db per customer and project with sort order~
- ~make query window scrollable, to big as is~
- ~move database logic to own class~
- ~Easy way to edit time row in post. For ex. change customer/project/git~
- ~Sort order of items in lists~
- ~Total time by customer~
- ~Quick selects from different tables~
- ~auto run SQL on tables in sql-query window~
- ~convert "iloc":s to use _get_value_from_df instead~
- ~minute timer also store "current date", if it is different from stored, updated SELECTED DATE to new value 
- ~Wage, cost, bonus not calculating correct~