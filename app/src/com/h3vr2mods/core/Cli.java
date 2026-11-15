package com.h3vr2mods.core;

import java.io.File;
import java.util.*;

/** Desktop test: java com.h3vr2mods.core.Cli <footlong.base.hdog> <outDir> <mod.h3mod>... */
public final class Cli {
    public static void main(String[] a) throws Exception {
        List<ModPackage> mods = new ArrayList<>();
        for (int i = 2; i < a.length; i++) {
            String[] parts = a[i].split("::"); ModPackage m = new ModPackage(new File(parts[0]));
            if (parts.length > 1) m.options.addAll(Arrays.asList(parts[1].split(",")));
            mods.add(m);
        }
        long t = System.currentTimeMillis();
        Patcher.Result r = Patcher.apply(new File(a[0]), mods, new File(a[1]), System.out::println);
        System.out.println("installed=" + r.installed + " skipped=" + r.skipped + " in " + (System.currentTimeMillis() - t) + " ms");
    }
}
