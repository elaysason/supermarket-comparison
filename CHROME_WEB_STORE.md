# Chrome Web Store Submission Notes

## Single purpose

Sal Kal compares the products and quantities in a user's cart on supported
supermarket websites and displays price and fulfillment comparisons from other
supported chains.

## Permission justifications

### `activeTab`

Used only when the user opens the extension popup so Sal Kal can identify
whether the current tab is a supported supermarket page and display the
appropriate status or navigation action.

### Supermarket host permissions

Access to Shufersal, Rami Levy, and Hazi Hinam pages is required to detect cart
pages, read product identifiers, names, and quantities, monitor cart changes,
and display the comparison widget. Access is limited to the supported
supermarket domains.

### API host permission

Access to the Sal Kal Cloud Run API is required to securely send cart details
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

> סל קל הוא שירות עצמאי ואינו קשור, ממומן או מופעל על ידי רשתות המזון
> המופיעות בתוסף. שמות הרשתות וסימניהן שייכים לבעליהם ומשמשים לזיהוי
> ולהשוואת מחירים בלבד.
