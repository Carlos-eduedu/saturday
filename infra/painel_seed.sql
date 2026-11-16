-- Casos que o banco local do painel não tem e que a tela precisa mostrar:
-- um alerta aberto e uma fala da IA com turno registrado. Pode rodar de novo.
--
--   docker exec -i saturday-postgres-1 psql -U saturday -d saturday_painel_dev < infra/painel_seed.sql
--
-- shortcut: usa a primeira conversa que já tem fala da IA; a oferta vigente
-- mora no checkpoint do grafo, então "Difere da oferta" só aparece depois de
-- uma jornada CLT pelo simulador. Vira script Python quando isso for preciso.

insert into alertas (tipo, conversa_id, detalhe)
select 'envio_falhou', m.conversa_id, '{}'::jsonb
from mensagens m
where m.autor = 'ia'
  and not exists (select 1 from alertas where resolvido_em is null)
order by m.id
limit 1;

with fala as (
  select id, conversa_id from mensagens
  where autor = 'ia' and turno_id is null
    and not exists (select 1 from mensagens where turno_id is not null)
  order by id
  limit 1
), turno as (
  insert into turnos (conversa_id, caminho, status, etapa, chamadas)
  select conversa_id, '["__start__", "present_offer"]'::jsonb, 'ok', 'oferta', '[]'::jsonb
  from fala
  returning id
)
update mensagens
set turno_id = (select id from turno), chave_mensagem = 'oferta'
where id = (select id from fala);
