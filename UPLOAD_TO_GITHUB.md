# Upload the app to GitHub

Use the **GITHUB_READY** source ZIP. Do not upload a PRIVATE_BACKUP ZIP, your JSON backups, the personal project folder, or `data/`.

1. Extract the source ZIP. Open the folder containing `app`, `static`, `render.yaml` and `requirements.txt`.
2. Create an empty repository in your GitHub account. A private repository is fine.
3. Use GitHub Desktop to add/publish the extracted source folder, or use **Add file → Upload files** on GitHub. Upload the extracted contents so `render.yaml` and `requirements.txt` are at the repository's top level. Uploading the ZIP itself only stores an archive; it does not unpack or deploy the app.
4. Include `.gitignore`, `.dockerignore`, `.python-version`, `firestore.rules` and `firebase.json`. If the browser hides dotfiles or rejects a large batch, use GitHub Desktop. GitHub's browser upload accepts up to 100 files per batch.
5. Continue with **FIREBASE_SETUP.md** to create the cloud sign-in/storage and connect the repository to the web host.

GitHub can also download your code to a phone: open the repository, choose **Code → Download ZIP**. This is a source-code copy, not your saved account data. Use the app's **Save JSON Backup** for personal data instead.

GitHub Pages hosts static HTML/CSS/JavaScript. This existing app needs its Python backend, so the live app URL will come from the backend host, not a GitHub Pages URL.

Official guides:

- https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository
- https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives
- https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
