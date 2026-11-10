update pages set translated_data = null, status = 'pending'
where book_id = '4dea8c96-a4b6-4034-acda-bac6a464d3bb'
  and page_number <= 16
  and (status <> 'completed'
       or exists (
         select 1
         from jsonb_array_elements(coalesce(translated_data->'lines','[]'::jsonb)) l,
              jsonb_array_elements(l) p
         where array_length(string_to_array(btrim(p->>'original'), ' '), 1) > 4
       ));