# Firebase setup for the headline study

This repo is configured to use Firebase for data collection when `VITE_STORAGE_ENGINE` is `firebase`.

Required values:

- `VITE_FIREBASE_CONFIG`: the Firebase web app config object from Project settings.
- `VITE_RECAPTCHAV3TOKEN`: the reCAPTCHA v3 site key used by Firebase App Check.
- `VITE_STORAGE_ENGINE`: `firebase`.

For GitHub Pages builds, add those same names as GitHub Actions repository variables. The deploy workflow passes them into `yarn build`.

Console setup checklist:

1. Enable Firestore Database.
2. Publish `firebase/firestore.rules`.
3. Enable Firebase Storage.
4. Publish `firebase/storage.rules`.
5. Enable Anonymous authentication for participants.
6. Enable Google authentication for study administrators.
7. Register App Check with reCAPTCHA v3 and add `localhost`, `127.0.0.1`, and the GitHub Pages domain.
8. Apply Storage CORS:

```sh
gsutil cors set firebase/cors.json gs://financial-uncertainty.firebasestorage.app
```
