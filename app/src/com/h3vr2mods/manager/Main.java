package com.h3vr2mods.manager;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.widget.*;

import com.h3vr2mods.core.*;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public class Main extends Activity {
    static final String GAME = "com.rustltd.h3vr2", TAG = "H3ModManager";
    static final File GAME_DIR = new File(Environment.getExternalStorageDirectory(), "Android/obb/" + GAME);
    static final File BASE = new File(GAME_DIR, "footlong.base.hdog");
    static final int PICK = 1;

    private LinearLayout list, online, banner; private ScrollView logBox; private TextView status, log;
    private Button apply, removeAll, access, addFile;
    private final Map<String, CheckBox> boxes = new LinkedHashMap<>();
    private final Map<String, CheckBox> optBoxes = new LinkedHashMap<>();   // "modId::optionId"
    private final Map<String, ModPackage> mods = new LinkedHashMap<>();
    private volatile boolean busy;
    private static boolean catalogChecked;   // once per app start

    // ------------------------------------------------------------------ layout

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        int pad = dp(16);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setPadding(pad, pad, pad, pad);
        root.setBackgroundColor(Color.rgb(18, 18, 22));
        TextView title = text("H3VR2 Mod Manager", 26, Color.WHITE); title.setTypeface(Typeface.DEFAULT_BOLD); root.addView(title);
        status = text("", 15, Color.rgb(190, 190, 200)); status.setPadding(0, dp(6), 0, dp(10)); root.addView(status);
        banner = new LinearLayout(this); banner.setOrientation(LinearLayout.VERTICAL); root.addView(banner);

        LinearLayout perms = new LinearLayout(this); perms.setOrientation(LinearLayout.HORIZONTAL);
        access = button("Allow access to game files", v -> openSettings(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES));
        addFile = button("Add mod file…", v -> pickFiles());
        perms.addView(addFile); perms.addView(access); root.addView(perms);

        ScrollView sv = new ScrollView(this);
        LinearLayout content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL);
        list = new LinearLayout(this); list.setOrientation(LinearLayout.VERTICAL); content.addView(list);
        online = new LinearLayout(this); online.setOrientation(LinearLayout.VERTICAL); content.addView(online);
        sv.addView(content);
        root.addView(sv, new LinearLayout.LayoutParams(-1, 0, 1f));

        LinearLayout actions = new LinearLayout(this); actions.setOrientation(LinearLayout.HORIZONTAL); actions.setPadding(0, dp(8), 0, dp(8));
        apply = button("Apply selection", v -> run(false)); removeAll = button("Remove all mods", v -> run(true));
        actions.addView(apply); actions.addView(removeAll); root.addView(actions);

        log = text("", 13, Color.rgb(150, 220, 150)); log.setTypeface(Typeface.MONOSPACE);
        logBox = new ScrollView(this); logBox.addView(log); logBox.setVisibility(View.GONE);
        root.addView(logBox, new LinearLayout.LayoutParams(-1, dp(110)));
        setContentView(root);
    }

    @Override protected void onResume() {
        super.onResume();
        Intent in = getIntent();
        if (in.hasExtra("catalog")) prefs().edit().putString("catalog_url", in.getStringExtra("catalog")).apply();   // testing/override
        if (!busy) refresh(true);
        if (in.hasExtra("importFile")) { importMod(Uri.fromFile(new File(in.getStringExtra("importFile")))); in.removeExtra("importFile"); refresh(false); }
        if (in.hasExtra("select")) {
            List<String> want = Arrays.asList(in.getStringExtra("select").split(","));
            for (Map.Entry<String, CheckBox> e : boxes.entrySet()) e.getValue().setChecked(want.contains(e.getKey()));
            for (Map.Entry<String, CheckBox> e : optBoxes.entrySet()) e.getValue().setChecked(want.contains(e.getKey()));
            in.removeExtra("select");
            if (in.getBooleanExtra("apply", false)) { in.removeExtra("apply"); run(false); }
        }
        if (in.hasExtra("snapshot")) { in.removeExtra("snapshot"); getWindow().getDecorView().postDelayed(this::snapshot, 2500); }
        if (!catalogChecked) { catalogChecked = true; checkCatalog(); }
    }

    @Override protected void onNewIntent(Intent i) {
        super.onNewIntent(i); setIntent(i);
        // app self-update: Android asks the user to confirm the install
        if (i.hasExtra(PackageInstaller.EXTRA_STATUS)) {
            int st = i.getIntExtra(PackageInstaller.EXTRA_STATUS, -1);
            if (st == PackageInstaller.STATUS_PENDING_USER_ACTION) { Intent c = i.getParcelableExtra(Intent.EXTRA_INTENT); if (c != null) startActivity(c); }
            else if (st != PackageInstaller.STATUS_SUCCESS) append("App update failed: " + i.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE));
        }
    }

    /** Debug aid: adb shell am start -n com.h3vr2mods.manager/.Main --ez snapshot true  ->  files/snap.png */
    private void snapshot() {
        try {
            View v = getWindow().getDecorView();
            Bitmap bm = Bitmap.createBitmap(v.getWidth(), v.getHeight(), Bitmap.Config.ARGB_8888);
            v.draw(new android.graphics.Canvas(bm));
            try (FileOutputStream o = new FileOutputStream(new File(getExternalFilesDir(null), "snap.png"))) { bm.compress(Bitmap.CompressFormat.PNG, 100, o); }
        } catch (Exception e) { Log.e(TAG, "snapshot", e); }
    }

    // ------------------------------------------------------------------ state of things

    private void refresh(boolean autoReapply) {
        PackageInfo game = gameInfo();
        boolean canAccess = GAME_DIR.list() != null;
        if (!canAccess && game != null && getPackageManager().canRequestPackageInstalls()) {
            // Android only applies the folder access to newly started processes: restart once
            if (!getIntent().getBooleanExtra("restarted", false)) { restart(); return; }
        }
        access.setVisibility(canAccess ? View.GONE : View.VISIBLE);
        loadMods();
        State st = State.load(this);
        StringBuilder s = new StringBuilder();
        if (game == null) s.append("Hot Dogs, Horseshoes & Hand Grenades 2 is not installed.\n");
        else s.append("Game version ").append(game.versionName).append("\n");
        if (game != null && !canAccess) s.append("Tap \"Allow access to game files\" and turn on \"Allow from this source\". This app needs it to put mod files in the game's folder.\n");
        if (canAccess && !BASE.exists()) s.append("Start the game once so it finishes downloading its content.\n");
        boolean installed = new File(GAME_DIR, Patcher.FIRST).exists();
        List<String> names = new ArrayList<>(); for (String id : st.mods) if (!id.contains("::")) names.add(mods.containsKey(id) ? mods.get(id).name : id);
        s.append(installed ? "Installed mods: " + (names.isEmpty() ? "?" : String.join(", ", names)) : "No mods installed.");
        s.append("\nClose the game before applying changes. Weapons appear in the item spawner under \"Modded\".");
        status.setText(s);
        for (Map.Entry<String, CheckBox> e : boxes.entrySet()) e.getValue().setChecked(st.mods.contains(e.getKey()));
        for (Map.Entry<String, CheckBox> e : optBoxes.entrySet()) e.getValue().setChecked(st.mods.contains(e.getKey()));
        boolean ready = game != null && canAccess && BASE.exists();
        apply.setEnabled(ready && !busy); removeAll.setEnabled(ready && installed && !busy);
        // after a game update the old add-on files no longer match: rebuild them from the new game files
        if (ready && autoReapply && installed && !st.matches(game, BASE)) {
            append("The game was updated since mods were installed; re-applying them for the new version…");
            run(false);
        }
    }

    private File importedDir() { File d = new File(getFilesDir(), "imported"); d.mkdirs(); return d; }

    private void loadMods() {
        mods.clear(); boxes.clear(); optBoxes.clear(); list.removeAllViews();
        List<File> files = new ArrayList<>();
        File bundled = new File(getFilesDir(), "mods"); bundled.mkdirs();
        long appTime = 0; try { appTime = getPackageManager().getPackageInfo(getPackageName(), 0).lastUpdateTime; } catch (Exception ignored) { }
        try {
            for (String n : getAssets().list("mods")) {
                File f = new File(bundled, n);
                if (!f.exists() || f.lastModified() < appTime) try (InputStream in = getAssets().open("mods/" + n); OutputStream o = new FileOutputStream(f)) { in.transferTo(o); }
                files.add(f);
            }
        } catch (IOException e) { append("Could not read bundled mods: " + e); }
        File[] l = importedDir().listFiles((d, n) -> n.endsWith(".h3mod")); if (l != null) files.addAll(Arrays.asList(l));
        for (File f : files) {
            try {
                ModPackage m = new ModPackage(f);
                ModPackage old = mods.get(m.id);
                if (old == null || m.version >= old.version) mods.put(m.id, m);   // newest copy wins
            } catch (Exception e) { append(f.getName() + ": " + e.getMessage()); }
        }
        for (ModPackage m : mods.values()) list.addView(row(m));
        if (mods.isEmpty()) list.addView(text("No mods yet. Tap \"Add mod file…\" to pick a .h3mod file.", 15, Color.LTGRAY));
    }

    private View row(ModPackage m) {
        LinearLayout r = new LinearLayout(this); r.setOrientation(LinearLayout.HORIZONTAL); r.setGravity(Gravity.CENTER_VERTICAL);
        r.setPadding(dp(8), dp(8), dp(8), dp(8)); r.setBackgroundColor(Color.rgb(30, 30, 38));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2); lp.setMargins(0, 0, 0, dp(6)); r.setLayoutParams(lp);
        CheckBox cb = new CheckBox(this); boxes.put(m.id, cb); r.addView(cb);
        byte[] icon = m.icon();
        if (icon != null) {
            Bitmap bm = BitmapFactory.decodeByteArray(icon, 0, icon.length);
            ImageView iv = new ImageView(this); iv.setImageBitmap(bm); iv.setAdjustViewBounds(true);
            r.addView(iv, new LinearLayout.LayoutParams(dp(150), dp(60)));
        }
        LinearLayout t = new LinearLayout(this); t.setOrientation(LinearLayout.VERTICAL); t.setPadding(dp(12), 0, 0, 0);
        TextView n = text(m.name, 18, Color.WHITE); n.setTypeface(Typeface.DEFAULT_BOLD); t.addView(n);
        if (!m.description.isEmpty()) t.addView(text(m.description, 13, Color.rgb(170, 170, 180)));
        for (Map<String, Object> o : m.optionList()) {
            CheckBox ob = new CheckBox(this); ob.setText((String) o.get("name")); ob.setTextSize(13); ob.setTextColor(Color.rgb(200, 200, 210));
            String key = m.id + "::" + o.get("id");
            optBoxes.put(key, ob);
            ob.setOnCheckedChangeListener((v, on) -> { if (on) cb.setChecked(true); });
            t.addView(ob);
        }
        r.addView(t, new LinearLayout.LayoutParams(0, -2, 1f));
        r.setOnClickListener(v -> cb.toggle());
        if (m.file.getParentFile().equals(importedDir())) {
            t.addView(text("Added from file or download. Long-press to remove from this list.", 12, Color.rgb(120, 170, 220)));
            r.setOnLongClickListener(v -> {
                new AlertDialog.Builder(this).setTitle("Remove " + m.name + "?")
                    .setMessage("It disappears from this list. If it's installed in the game, tap Apply selection afterwards to take it out.")
                    .setPositiveButton("Remove", (d, w) -> { m.file.delete(); refresh(false); })
                    .setNegativeButton("Cancel", null).show();
                return true;
            });
        }
        return r;
    }

    // ------------------------------------------------------------------ adding mods from files

    /** Opens the system file picker (Downloads, any folder, USB storage…) to choose .h3mod files. */
    private void pickFiles() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE); i.setType("*/*");
        i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        try { startActivityForResult(i, PICK); } catch (Exception e) { append("No file picker available: " + e); }
    }

    @Override protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req != PICK || res != RESULT_OK || data == null) return;
        List<Uri> uris = new ArrayList<>();
        if (data.getClipData() != null) for (int k = 0; k < data.getClipData().getItemCount(); k++) uris.add(data.getClipData().getItemAt(k).getUri());
        else if (data.getData() != null) uris.add(data.getData());
        for (Uri u : uris) importMod(u);
        refresh(false);
    }

    /** Copies a picked file into the app, checks it is a valid mod, and keeps it under its mod id. */
    private void importMod(Uri u) {
        File tmp = new File(importedDir(), "incoming.tmp");
        try {
            try (InputStream in = getContentResolver().openInputStream(u); OutputStream o = new FileOutputStream(tmp)) { in.transferTo(o); }
            ModPackage m = keep(tmp);
            append("Added " + m.name + ". Tick it and tap Apply selection.");
        } catch (Exception e) {
            tmp.delete();
            append("Couldn't add " + u.getLastPathSegment() + ": not a valid .h3mod (" + e.getMessage() + ")");
        }
    }

    private ModPackage keep(File tmp) throws IOException {
        ModPackage m = new ModPackage(tmp);
        File dst = new File(importedDir(), m.id.replaceAll("[^A-Za-z0-9_.-]", "_") + ".h3mod");
        dst.delete();
        if (!tmp.renameTo(dst)) throw new IOException("could not store the mod");
        return new ModPackage(dst);
    }

    // ------------------------------------------------------------------ online catalog

    private SharedPreferences prefs() { return getSharedPreferences("settings", MODE_PRIVATE); }
    private String catalogUrl() { return prefs().getString("catalog_url", Catalog.DEFAULT_URL); }

    /** Fetches the catalog; updates downloaded mods automatically and offers new mods and app updates. */
    private void checkCatalog() {
        String url = catalogUrl();
        if (url == null || url.isEmpty()) return;
        new Thread(() -> {
            try {
                Catalog c = Catalog.fetch(url);
                // automatic updates of mods the player already has
                List<String> updated = new ArrayList<>();
                Map<String, ModPackage> have = new HashMap<>(mods);
                for (Catalog.Entry e : c.mods) {
                    ModPackage m = have.get(e.id);
                    if (m == null || e.version <= m.version) continue;
                    File tmp = new File(importedDir(), "download.tmp");
                    Catalog.download(e.url, tmp);
                    keep(tmp); updated.add(e.name);
                }
                runOnUiThread(() -> {
                    if (!updated.isEmpty()) {
                        append("Updated: " + String.join(", ", updated));
                        refresh(false);
                        State st = State.load(this);
                        boolean installedOne = false; for (String n : st.mods) for (ModPackage m : mods.values()) if (m.id.equals(n) && updated.contains(m.name)) installedOne = true;
                        if (installedOne && new File(GAME_DIR, Patcher.FIRST).exists()) { append("Re-applying updated mods…"); run(false); }
                    }
                    showCatalog(c);
                });
            } catch (Exception e) { Log.w(TAG, "catalog", e); append("Couldn't check for online mods (" + e.getMessage() + ")"); }
        }).start();
    }

    private void showCatalog(Catalog c) {
        online.removeAllViews(); banner.removeAllViews();
        long mine = 0; try { mine = getPackageManager().getPackageInfo(getPackageName(), 0).getLongVersionCode(); } catch (Exception ignored) { }
        if (c.app != null && c.app.versionCode > mine && c.app.url != null) {
            Button up = button("Update the mod manager to " + (c.app.versionName == null ? "the latest version" : c.app.versionName), v -> updateApp(c.app));
            banner.addView(up);
            if (c.app.notes != null) banner.addView(text(c.app.notes, 13, Color.rgb(170, 200, 240)));
        }
        List<Catalog.Entry> fresh = new ArrayList<>();
        for (Catalog.Entry e : c.mods) if (!mods.containsKey(e.id)) fresh.add(e);
        if (fresh.isEmpty()) return;
        TextView h = text("Available online", 18, Color.WHITE); h.setTypeface(Typeface.DEFAULT_BOLD); h.setPadding(0, dp(10), 0, dp(6));
        online.addView(h);
        for (Catalog.Entry e : fresh) {
            LinearLayout r = new LinearLayout(this); r.setOrientation(LinearLayout.HORIZONTAL); r.setGravity(Gravity.CENTER_VERTICAL);
            r.setPadding(dp(8), dp(8), dp(8), dp(8)); r.setBackgroundColor(Color.rgb(26, 30, 40));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2); lp.setMargins(0, 0, 0, dp(6)); r.setLayoutParams(lp);
            LinearLayout t = new LinearLayout(this); t.setOrientation(LinearLayout.VERTICAL);
            TextView n = text(e.name == null ? e.id : e.name, 17, Color.WHITE); n.setTypeface(Typeface.DEFAULT_BOLD); t.addView(n);
            String sub = (e.description == null ? "" : e.description) + (e.size > 0 ? String.format(Locale.US, "  (%.1f MB)", e.size / 1e6) : "");
            t.addView(text(sub, 13, Color.rgb(170, 170, 180)));
            r.addView(t, new LinearLayout.LayoutParams(0, -2, 1f));
            Button dl = button("Download", null);
            dl.setOnClickListener(v -> {
                dl.setEnabled(false); dl.setText("Downloading…");
                new Thread(() -> {
                    try {
                        File tmp = new File(importedDir(), "download.tmp");
                        Catalog.download(e.url, tmp); ModPackage m = keep(tmp);
                        append("Downloaded " + m.name + ". Tick it and tap Apply selection.");
                        runOnUiThread(() -> { refresh(false); showCatalog(c); });
                    } catch (Exception x) { append("Download failed: " + x.getMessage()); runOnUiThread(() -> { dl.setEnabled(true); dl.setText("Download"); }); }
                }).start();
            });
            r.addView(dl);
            online.addView(r);
        }
    }

    /** Downloads the new APK and hands it to Android's installer (the player confirms). */
    private void updateApp(Catalog.App a) {
        append("Downloading the new version of the mod manager…");
        new Thread(() -> {
            try {
                byte[] apk = Catalog.get(a.url);
                PackageInstaller pi = getPackageManager().getPackageInstaller();
                PackageInstaller.SessionParams p = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
                p.setAppPackageName(getPackageName());
                int id = pi.createSession(p);
                try (PackageInstaller.Session s = pi.openSession(id)) {
                    try (OutputStream o = s.openWrite("update.apk", 0, apk.length)) { o.write(apk); s.fsync(o); }
                    Intent cb = new Intent(this, Main.class).setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
                    PendingIntent pend = PendingIntent.getActivity(this, 7, cb, PendingIntent.FLAG_MUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
                    s.commit(pend.getIntentSender());
                }
            } catch (Exception e) { append("App update failed: " + e.getMessage()); }
        }).start();
    }

    // ------------------------------------------------------------------ applying

    private void run(boolean removeEverything) {
        if (busy) return;
        busy = true; apply.setEnabled(false); removeAll.setEnabled(false);
        List<ModPackage> chosen = new ArrayList<>();
        List<String> selection = new ArrayList<>();
        if (!removeEverything) for (Map.Entry<String, CheckBox> e : boxes.entrySet()) {
            if (!e.getValue().isChecked()) continue;
            ModPackage m = mods.get(e.getKey());
            m.options.clear();
            for (Map.Entry<String, CheckBox> o : optBoxes.entrySet())
                if (o.getKey().startsWith(m.id + "::") && o.getValue().isChecked()) { m.options.add(o.getKey().substring(m.id.length() + 2)); selection.add(o.getKey()); }
            chosen.add(m);
        }
        new Thread(() -> {
            try {
                PackageInfo game = gameInfo();
                if (chosen.isEmpty()) {
                    Patcher.uninstall(GAME_DIR); State.save(this, new ArrayList<>(), game, BASE);
                    append("All mods removed. The game is back to normal.");
                } else {
                    Patcher.Result r = Patcher.apply(BASE, chosen, GAME_DIR, this::append);
                    List<String> ids = new ArrayList<>();
                    for (ModPackage m : chosen) if (r.installed.contains(m.name)) {
                        ids.add(m.id);
                        for (String s : selection) if (s.startsWith(m.id + "::")) ids.add(s);
                    }
                    State.save(this, ids, game, BASE);
                    for (Map.Entry<String, String> e : r.skipped.entrySet()) append("Not installed: " + e.getKey() + " (" + e.getValue() + ")");
                    if (!r.installed.isEmpty()) append("Done! Start the game. Weapons are in the item spawner under \"Modded\".");
                }
            } catch (Throwable t) {
                Log.e(TAG, "apply failed", t);
                append("Failed: " + t);
                Patcher.uninstall(GAME_DIR);
                append("Mod files removed so the game still starts normally.");
            } finally {
                busy = false; runOnUiThread(() -> refresh(false));
            }
        }).start();
    }

    // ------------------------------------------------------------------ helpers

    private void restart() {
        Intent i = Intent.makeRestartActivityTask(new android.content.ComponentName(this, Main.class));
        i.putExtra("restarted", true);
        startActivity(i);
        Runtime.getRuntime().exit(0);
    }

    private PackageInfo gameInfo() { try { return getPackageManager().getPackageInfo(GAME, 0); } catch (PackageManager.NameNotFoundException e) { return null; } }

    private void openSettings(String action) {
        try { startActivity(new Intent(action, Uri.parse("package:" + getPackageName()))); }
        catch (Exception e) { startActivity(new Intent(action)); }
    }

    private void append(String s) {
        Log.i(TAG, s);
        runOnUiThread(() -> { logBox.setVisibility(View.VISIBLE); log.append(s + "\n"); logBox.post(() -> logBox.fullScroll(View.FOCUS_DOWN)); });
    }

    private TextView text(String s, int sp, int color) { TextView t = new TextView(this); t.setText(s); t.setTextSize(sp); t.setTextColor(color); return t; }
    private Button button(String s, View.OnClickListener l) { Button b = new Button(this); b.setText(s); b.setAllCaps(false); if (l != null) b.setOnClickListener(l); return b; }
    private int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }

    /** What we installed last time (mod ids and "id::option"), and for which game files. */
    static final class State {
        List<String> mods = new ArrayList<>(); long versionCode = -1, baseSize = -1, baseTime = -1;

        static State load(Activity a) {
            State s = new State();
            try {
                File f = new File(a.getFilesDir(), "state.json"); if (!f.exists()) return s;
                Map<String, Object> m = Json.obj(Json.parse(new String(java.nio.file.Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8)));
                for (Object o : Json.arr(m.get("mods"))) s.mods.add((String) o);
                s.versionCode = (Long) m.get("versionCode"); s.baseSize = (Long) m.get("baseSize"); s.baseTime = (Long) m.get("baseTime");
            } catch (Exception ignored) { }
            return s;
        }

        static void save(Activity a, List<String> mods, PackageInfo game, File base) throws IOException {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("mods", new ArrayList<Object>(mods));
            m.put("versionCode", game == null ? -1L : game.getLongVersionCode());
            m.put("baseSize", base.length()); m.put("baseTime", base.lastModified());
            try (FileOutputStream o = new FileOutputStream(new File(a.getFilesDir(), "state.json"))) { o.write(Json.write(m).getBytes(StandardCharsets.UTF_8)); }
        }

        boolean matches(PackageInfo game, File base) {
            return game != null && game.getLongVersionCode() == versionCode && base.length() == baseSize && base.lastModified() == baseTime;
        }
    }
}
