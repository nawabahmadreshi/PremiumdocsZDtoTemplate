# Premium Documentation Hub

A portable, beautifully styled documentation hub for Aquera. This project transforms Zendesk help articles into a premium, responsive local documentation experience and packages it into a portable macOS application for easy distribution.

## 🚀 For End-Users (How to use)

If you have received the **Aquera_Hub_Portable.zip** file, follow these steps to view the documentation:

1.  **Unzip**: Extract the `A_Hub_Portable.zip` file to your folder of choice.
2.  **Launch**: Right-click on **`A Hub.app`** and select **Open** (the first time you open it, macOS may ask for confirmation—simply click "Open").
3.  **Wait for Setup**: A terminal window will briefly appear to ensure you have the necessary components.
4.  **View**: Your default browser will automatically open to `http://127.0.0.1:5001`, where you can browse the documentation.

> **Note**: You must have Python 3 installed on your Mac for the launcher to work.

---

## 🛠 For Developers / Documentation Managers

### Project Structure
- `app/`: The Flask backend and documentation processor.
- `app/static/`: CSS and HTML templates for the premium look.
- `Identity_Survey_Hub_Styled.html`: The final generated documentation file.
- `apply_premium_style.py`: The core script that applies the premium template to the raw content.
- `sync_premium_doc.py`: Fetches the latest content from Zendesk.

### Updating the Documentation
To pull the latest changes from Zendesk and re-apply the premium styling:

1.  **Sync from Zendesk**:
    ```bash
    python3 sync_premium_doc.py
    ```
2.  **Apply Premium Styling**:
    ```bash
    python3 apply_premium_style.py
    ```

### Rebuilding the Portable App
If you have updated the styles or the documentation content, you should sync it to the app bundle before redistributing:

1.  Copy the updated files into the bundle:
    ```bash
    cp app/static/template.html "Aquera Hub.app/Contents/Resources/project/app/static/"
    cp app/static/viewer.css "Aquera Hub.app/Contents/Resources/project/app/static/"
    cp Identity_Survey_Hub_Styled.html "Aquera Hub.app/Contents/Resources/project/"
    ```
2.  Re-zip the app:
    ```bash
    zip -r Aquera_Hub_Portable.zip "Aquera Hub.app"
    ```

## ✨ UI Improvements
- **Clean Layout**: No dashed section dividers.
- **Minimalist Tables**: Transparent backgrounds with bold headers for a professional look.
- **Responsive Design**: Works perfectly on mobile and desktop.
- **Sticky Headers**: Section titles stay visible while scrolling for easy navigation.

---
© 2026 Aquera Documentation Hub
