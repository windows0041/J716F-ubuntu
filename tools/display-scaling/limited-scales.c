/* SPDX-License-Identifier: MIT
 * Keep GNOME Settings' built-in DSI scale choices at 100/150/200 percent.
 * The compositor remains responsible for native scale validation/apply/revert.
 * Load only in gnome-control-center, never globally or in gnome-shell.
 */
#define _GNU_SOURCE
#include <gio/gio.h>
#include <dlfcn.h>
#include <math.h>
#include <string.h>

typedef void (*CallFunc) (GDBusConnection *, const gchar *, const gchar *,
                         const gchar *, const gchar *, GVariant *,
                         const GVariantType *, GDBusCallFlags, gint,
                         GCancellable *, GAsyncReadyCallback, gpointer);
typedef GVariant *(*FinishFunc) (GDBusConnection *, GAsyncResult *, GError **);
static CallFunc original_call;
static FinishFunc original_finish;
static GQuark tagged_reply;

typedef struct {
  GAsyncReadyCallback callback;
  gpointer user_data;
} PendingCall;

__attribute__((constructor)) static void
resolve_originals (void)
{
  original_call = (CallFunc) dlsym (RTLD_NEXT, "g_dbus_connection_call");
  original_finish = (FinishFunc) dlsym (RTLD_NEXT, "g_dbus_connection_call_finish");
  tagged_reply = g_quark_from_static_string ("j716f-display-scaling-current-state");
}

/* Return an owned tuple while preserving every other field verbatim. */
static GVariant *
replace_child (GVariant *tuple, gsize index, GVariant *replacement)
{
  gsize count = g_variant_n_children (tuple);
  GVariant **children = g_new (GVariant *, count);
  GVariant *result;
  for (gsize i = 0; i < count; i++)
    children[i] = i == index ? g_variant_ref (replacement)
                            : g_variant_get_child_value (tuple, i);
  result = g_variant_ref_sink (g_variant_new_tuple (children, count));
  for (gsize i = 0; i < count; i++)
    g_variant_unref (children[i]);
  g_free (children);
  return result;
}

static GVariant *
filter_mode (GVariant *mode)
{
  g_autoptr(GVariant) scales = g_variant_get_child_value (mode, 5);
  g_autoptr(GVariant) filtered = NULL;
  GVariantBuilder builder;
  guint seen = 0, count = 0;
  gdouble values[3] = {0};
  g_variant_builder_init (&builder, G_VARIANT_TYPE ("ad"));
  for (gsize i = 0; i < g_variant_n_children (scales); i++)
    {
      gdouble value;
      gint quarter, slot;
      g_variant_get_child (scales, i, "d", &value);
      quarter = (gint) round (value * 4);
      slot = quarter == 4 ? 0 : quarter == 6 ? 1 : quarter == 8 ? 2 : -1;
      if (slot < 0 || fabs (value - (1.0 + slot * 0.5)) > 0.04 ||
          (seen & (1u << slot)))
        continue;
      seen |= 1u << slot;
      values[slot] = value;
      count++;
      /* Preserve the compositor's exact value: 150% is ~1.502347 here. */
      g_variant_builder_add (&builder, "d", value);
    }
  if (count == 0)
    {
      g_variant_builder_clear (&builder);
      return g_variant_ref (mode);
    }
  filtered = g_variant_ref_sink (g_variant_builder_end (&builder));
  g_message ("J716F display scaling: %u choices; native values %.9g %.9g %.9g",
             count, values[0], values[1], values[2]);
  return replace_child (mode, 5, filtered);
}

static GVariant *
filter_monitor (GVariant *monitor)
{
  g_autoptr(GVariant) spec = g_variant_get_child_value (monitor, 0);
  g_autoptr(GVariant) connector = g_variant_get_child_value (spec, 0);
  g_autoptr(GVariant) props = g_variant_get_child_value (monitor, 2);
  g_autoptr(GVariant) modes = NULL;
  g_autoptr(GVariant) filtered = NULL;
  gboolean builtin = FALSE;
  GVariantBuilder builder;
  g_variant_lookup (props, "is-builtin", "b", &builtin);
  if (!builtin || !g_str_has_prefix (g_variant_get_string (connector, NULL), "DSI-"))
    return g_variant_ref (monitor);
  modes = g_variant_get_child_value (monitor, 1);
  g_variant_builder_init (&builder, g_variant_get_type (modes));
  for (gsize i = 0; i < g_variant_n_children (modes); i++)
    {
      g_autoptr(GVariant) mode = g_variant_get_child_value (modes, i);
      g_autoptr(GVariant) updated = filter_mode (mode);
      g_variant_builder_add_value (&builder, updated);
    }
  filtered = g_variant_ref_sink (g_variant_builder_end (&builder));
  return replace_child (monitor, 1, filtered);
}

static GVariant *
filter_state (GVariant *state)
{
  const GVariantType *type = G_VARIANT_TYPE (
    "(ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv})");
  g_autoptr(GVariant) monitors = NULL;
  g_autoptr(GVariant) filtered = NULL;
  GVariantBuilder builder;
  if (!g_variant_is_of_type (state, type))
    return g_variant_ref (state);  /* Safe fallback after incompatible upgrades. */
  monitors = g_variant_get_child_value (state, 1);
  g_variant_builder_init (&builder, g_variant_get_type (monitors));
  for (gsize i = 0; i < g_variant_n_children (monitors); i++)
    {
      g_autoptr(GVariant) monitor = g_variant_get_child_value (monitors, i);
      g_autoptr(GVariant) updated = filter_monitor (monitor);
      g_variant_builder_add_value (&builder, updated);
    }
  filtered = g_variant_ref_sink (g_variant_builder_end (&builder));
  return replace_child (state, 1, filtered);
}

static void
current_state_ready (GObject *source, GAsyncResult *result, gpointer user_data)
{
  PendingCall *pending = user_data;
  if (G_IS_OBJECT (result))
    g_object_set_qdata (G_OBJECT (result), tagged_reply, GINT_TO_POINTER (1));
  pending->callback (source, result, pending->user_data);
  g_free (pending);
}

void
g_dbus_connection_call (GDBusConnection *connection, const gchar *bus_name,
                        const gchar *object_path, const gchar *interface_name,
                        const gchar *method_name, GVariant *parameters,
                        const GVariantType *reply_type, GDBusCallFlags flags,
                        gint timeout_msec, GCancellable *cancellable,
                        GAsyncReadyCallback callback, gpointer user_data)
{
  if (callback && g_strcmp0 (bus_name, "org.gnome.Mutter.DisplayConfig") == 0 &&
      g_strcmp0 (object_path, "/org/gnome/Mutter/DisplayConfig") == 0 &&
      g_strcmp0 (interface_name, "org.gnome.Mutter.DisplayConfig") == 0 &&
      g_strcmp0 (method_name, "GetCurrentState") == 0)
    {
      PendingCall *pending = g_new (PendingCall, 1);
      *pending = (PendingCall) {callback, user_data};
      original_call (connection, bus_name, object_path, interface_name,
                     method_name, parameters, reply_type, flags, timeout_msec,
                     cancellable, current_state_ready, pending);
      return;
    }
  original_call (connection, bus_name, object_path, interface_name, method_name,
                 parameters, reply_type, flags, timeout_msec, cancellable,
                 callback, user_data);
}

GVariant *
g_dbus_connection_call_finish (GDBusConnection *connection, GAsyncResult *result,
                               GError **error)
{
  GVariant *state = original_finish (connection, result, error);
  GVariant *filtered;
  if (!state || !G_IS_OBJECT (result) ||
      !g_object_get_qdata (G_OBJECT (result), tagged_reply))
    return state;
  filtered = filter_state (state);
  g_variant_unref (state);
  return filtered;
}
