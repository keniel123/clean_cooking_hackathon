# GridCook Mobile UI

A framework-free, mobile-first user interface for the household side of the GridCook clean-cooking project.

## Included functionality

- User ID and user name
- Monthly electricity usage in kWh
- Available credit in Kenyan shillings (KES)
- Profile photo in the top-right corner
- Twenty-four selectable hourly cooking slots, from 12:00 AM to 11:00 PM
- Multi-slot selection
- GO button
- Lower-cost slots shown in green
- Average-cost slots shown in amber
- Peak-cost slots shown in red
- Recommendation based on the user's selected slots
- Accessible buttons and mobile-responsive layout
- Hooks for future database, AI, tariff, and web-server integration

## Add it to your UI branch

From the root of your cloned repository:

```bash
git switch your-ui-branch
mkdir -p mobile-app
```

Copy all files from this package into `mobile-app/`, then run:

```bash
git add mobile-app
git commit -m "Add mobile cooking time-slot UI"
git push origin your-ui-branch
```

## Preview locally

From the repository root:

```bash
python3 -m http.server 8000
```

Open:

```text
http://localhost:8000/mobile-app/
```

## Demo assumptions

The current user and tariff values are placeholders:

- User: Amina Njeri
- User ID: KC-2048
- Electricity usage: 42.6 kWh
- Credit: KES 1,250
- Green: lower-cost periods
- Amber: average-cost periods
- Red: peak-cost periods

These assumptions are intentionally kept in `app.js`, not in the HTML.

## Replace the user data later

The database or API team can call:

```javascript
window.GridCookUI.setUserData({
  id: "KC-3001",
  name: "New User",
  electricityUsageKwh: 31.8,
  creditKes: 980,
  profilePhotoUrl: "/images/user-3001.jpg"
});
```

## Replace the hourly tariff/AI output later

The future service should provide exactly 24 entries:

```javascript
const tariffs = [
  { hour: 0, level: "low", rateKesPerKwh: 17 },
  { hour: 1, level: "low", rateKesPerKwh: 17 },
  // ...
  { hour: 18, level: "high", rateKesPerKwh: 38 },
  // ...
  { hour: 23, level: "medium", rateKesPerKwh: 25 }
];

window.GridCookUI.setHourlyTariffs(tariffs);
```

Allowed `level` values are:

- `low`
- `medium`
- `high`

## Read the selected slots

The integration team can retrieve the user's current selection:

```javascript
const selectedHours = window.GridCookUI.getSelectedHours();
```

It returns a sorted array such as:

```javascript
[10, 11, 18]
```

## Files

```text
mobile-app/
├── index.html
├── styles.css
├── app.js
├── README.md
└── assets/
    └── profile-photo.svg
```

This folder does not replace the existing management dashboard. It can be developed and reviewed independently, then connected to the shared services later.
