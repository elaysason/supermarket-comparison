# Chrome Web Store Submission Notes

## Version 1.1.1 — Sal Navon rebrand

- Upload package: `dist/salnavon-extension-1.1.1.zip`.
- Small promotional tile: `store-assets/promo-440x280.png` (440 × 280).
- Screenshot: `store-assets/screenshot-1280x800.png` (1280 × 800). The existing
  screenshot uses the retained cart-and-magnifier icon and contains no old brand
  name.
- Store icon: `extension/icons/icon128.png` (128 × 128).
- Release summary: renamed to סל נבון / Sal Navon, refreshed the popup tagline
  and promotional tile, and updated the privacy policy and supporting text.

Upload this package as an update to the existing extension listing to retain
the extension ID. Publish the updated privacy policy before submitting.

## Store listing copy

### Name

סל נבון

### Short description

משווה את סל הקניות שלך בין רשתות נתמכות ומראה איפה משתלם יותר להזמין.

### Detailed description

סל נבון — אותו סל, פחות כסף.

כבר מילאתם עגלה בסופר אונליין? סל נבון משווה את המוצרים והכמויות בעגלה
למחירים ברשתות אחרות, ישירות מתוך עמוד הקניות.

• ההשוואה מופיעה אוטומטית בעמודי עגלה נתמכים בשופרסל, רמי לוי וחצי חינם.
• התאמת מוצרים לפי ברקוד, ללא החלפה אוטומטית במוצרים אחרים.
• השוואת עלויות משלוח או איסוף עצמי כשנתונים אלה זמינים.
• הצגת מוצרים חסרים ומגבלות מינימום הזמנה כדי להבין את ההבדלים בין הרשתות.

לאחר ההתקנה, פתחו עגלת קניות באחד האתרים הנתמכים. חלון התוסף מציג אם
העמוד נתמך ומאפשר לעבור לעגלה או לרענן את העמוד.

ההשוואה מבוססת על נתוני המחירים הזמינים לשירות. הרשת הזולה ביותר משתנה
לפי המוצרים, זמינות הנתונים ותנאי האספקה. המחיר הסופי ותנאי ההזמנה נקבעים
באתר הרשת; חיסכון אינו מובטח בכל סל.

סל נבון הוא שירות עצמאי ואינו קשור, ממומן או מופעל על ידי רשתות המזון
המופיעות בתוסף. שמות הרשתות וסימניהן שייכים לבעליהם ומשמשים לזיהוי
ולהשוואת מחירים בלבד.

## Single purpose

Sal Navon compares the products and quantities in a user's cart on supported
supermarket websites and displays price and fulfillment comparisons from other
supported chains.

## Permission justifications

### `activeTab`

Used only when the user opens the extension popup so Sal Navon can identify
whether the current tab is a supported supermarket page and display the
appropriate status or navigation action.

### Supermarket host permissions

Access to Shufersal, Rami Levy, and Hazi Hinam pages is required to detect cart
pages, read product identifiers, names, and quantities, monitor cart changes,
and display the comparison widget. Access is limited to the supported
supermarket domains.

### API host permission

Access to the Sal Navon Cloud Run API is required to securely send cart details
for comparison and retrieve the resulting price comparison. Requests use
HTTPS.

## Data use disclosure

Declare **Website content** because the extension reads and transmits product
identifiers, product names, quantities, and the current supermarket chain from
supported cart pages.

The data is used only to provide the user-requested price comparison. It is not
sold, used for advertising or credit decisions, or used for unrelated purposes.
Complete the Chrome Web Store Limited Use certifications accordingly.

## Remote code

Select **No, I am not using remote code**. The extension's executable logic is
included in the submitted package. The remote API returns comparison data, not
executable code.

## Privacy policy URL

After `PRIVACY.md` is committed and pushed to the public repository, use:

https://github.com/elaysason/supermarket-comparison/blob/main/PRIVACY.md

## Listing disclaimer

Add this note to the detailed description:

> סל נבון הוא שירות עצמאי ואינו קשור, ממומן או מופעל על ידי רשתות המזון
> המופיעות בתוסף. שמות הרשתות וסימניהן שייכים לבעליהם ומשמשים לזיהוי
> ולהשוואת מחירים בלבד.
