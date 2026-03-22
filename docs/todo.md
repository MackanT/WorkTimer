## Features
 ### TimeTracker
- Easy way to add time in post.
- update customer/project should also update times values!
- Marker for ongoing projects? Make it easier to see from a glance what is active right now
- At midnight, date "today" does not switch automatically. Might be fixed but have not verified it (bug)
 ### Database / QueryEditor
- Make PAT-tokens etc masked (not easily possible)
- no info when running for ex. delete command in query (bug)
- Create/Alter/Update table does not send "success message" (same for all with "no result set" returns)
 ### Devops
- Devops visualize as dag?
- Devops see board?
- Devops move items between columns (todo, analyze, in progress, review, test, done etc.)?
- Be able to post images/files when creating devops epic/feature/user-story (low priority!)
- Git id dropdown currently only exists in project close. missing in query-view and add-data view (maybe add there as well?)
- Defaults to first project available per organisation-url
- If internet does not exist on boot errors on devops client and it will never try to reconnect (bug)
- If no customers have devops integration when starting program it is not enabled. When then adding a devops customer, it is not auto-enabled (bug)
 ### Tasks
- Tasks missing delete task option?
- Tasks sort order not correct (?)
 ### Notes
- Notepad++ functionality + markdown (?)
- Page with 2 halfes, one with markdown input and the other a visualizer (better if one can edit directly in markdown viewer/visualizer!) Basically want notepad++ function in the app where you can create "notebooks" add text and leave and it is auto-saved, go back and it is always there etc.
 ### Documentation
- Go over all documentation in /docs and remove old docs, add new, ensure it is up to date and correct etc. 
 ### Generic
- Go over page layouts (ensure consistent ui sizes etc)
- Cleanup config_ui_styles
 ### BUGS
- Updating from settings does not call event to update in add-data page (i.e. newly added customers are not visible in its drop-downs)
- Default assignee not utilized