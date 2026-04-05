## Features

#### TimeTracker
- ~~Easy way to add time in post.~~
- update customer/project should also update times values!
- ~~Marker for ongoing projects? Make it easier to see from a glance what is active right now~~
- At midnight, date "today" does not switch automatically. Might be fixed but have not verified it (bug)
- Have active tasks/trackers on top of page, easily visible (?)
- Indicator in navigator on number of active trackers?

#### Database / QueryEditor
- Make PAT-tokens etc masked (not easily possible)
- ~~no info when running for ex. delete command in query (bug)~~
- ~~Create/Alter/Update table does not send "success message" (same for all with "no result set" returns)~~

#### Devops
- Devops visualize as dag?
- Devops see board?
- ~~Devops move items between columns (todo, analyze, in progress, review, test, done etc.)?~~
- Be able to post images/files when creating devops epic/feature/user-story (low priority!)
- Git id dropdown currently only exists in project close. missing in query-view and add-data view (maybe add there as well?)
- Defaults to first project available per organisation-url
- ~~If internet does not exist on boot errors on devops client and it will never try to reconnect (bug)~~
- ~~If no customers have devops integration when starting program it is not enabled. When then adding a devops customer, it is not auto-enabled (bug)~~
- ~~Tag (new added in config file) did not appear in devops~~

#### Tasks
- Tasks missing delete task option?

#### Notes
- Notepad++ functionality + markdown (?)
- remove exces vertical white-space
- ~~Paste images~~

#### Documentation
- Go over all documentation in /docs and remove old docs, add new, ensure it is up to date and correct etc. 

#### Generic
- Go over page layouts (ensure consistent ui sizes etc)
- Consistent "page height", currently hardcoded on every page....
- ~~Cleanup config_ui_styles~~

#### Settings
- Make it actually nice and usable.....
- Make config updateable via settings
- ~~On first load, devops-contacts is not auto-created after adding devops connection~~
- ~~Set default assignee is broken right now~~
- Set default what features to enable (data input/query editor/tasks/notepad etc)

#### BUGS
- ~~Updating from settings does not call event to update in add-data page (i.e. newly added customers are not visible in its drop-downs)~~
- ~~Default assignee not utilized~~
- ~~Drop-downs currently show all options if parent is blank. Should show blank until parent is selected~~
- ~~Pasting images into notepad in chromium based browsers does not work~~